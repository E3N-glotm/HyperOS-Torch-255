#define _GNU_SOURCE

#include <android/log.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <sched.h>
#include <signal.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mount.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

#define LOG_TAG "HyperTorch255"
#define TRIP_ON_MC 80000
#define TRIP_OFF_MC 75000
#define STOCK_BRIGHTNESS 76
#define DEFAULT_POLL_MS 100
#define MAX_PATH_LEN 512
#define POWERKEEPER_PROCESS "com.miui.powerkeeper"
#define TEMP_STATE_PATH "/sys/class/thermal/thermal_message/temp_state"

static volatile sig_atomic_t g_running = 1;

static void on_signal(int signo) {
    (void)signo;
    g_running = 0;
}

static void trim_line(char *s) {
    size_t n = strlen(s);
    while (n > 0 && (s[n - 1] == '\n' || s[n - 1] == '\r' || s[n - 1] == ' ' || s[n - 1] == '\t')) {
        s[--n] = '\0';
    }
}

static bool read_text(const char *path, char *buf, size_t size) {
    if (size < 2) {
        return false;
    }
    int fd = open(path, O_RDONLY | O_CLOEXEC);
    if (fd < 0) {
        return false;
    }
    ssize_t n = read(fd, buf, size - 1);
    int saved_errno = errno;
    close(fd);
    errno = saved_errno;
    if (n <= 0) {
        return false;
    }
    buf[n] = '\0';
    trim_line(buf);
    return true;
}

static bool read_int(const char *path, int *value) {
    char buf[64];
    if (!read_text(path, buf, sizeof(buf))) {
        return false;
    }
    char *end = NULL;
    errno = 0;
    long parsed = strtol(buf, &end, 10);
    if (errno != 0 || end == buf || *end != '\0' || parsed < -2147483647L - 1L || parsed > 2147483647L) {
        return false;
    }
    *value = (int)parsed;
    return true;
}

static bool write_int(const char *path, int value) {
    int fd = open(path, O_WRONLY | O_CLOEXEC);
    if (fd < 0) {
        return false;
    }
    struct stat st;
    if (fstat(fd, &st) == 0 && S_ISREG(st.st_mode)) {
        (void)ftruncate(fd, 0);
        (void)lseek(fd, 0, SEEK_SET);
    }
    char buf[32];
    int len = snprintf(buf, sizeof(buf), "%d\n", value);
    bool ok = len > 0 && len < (int)sizeof(buf) && write(fd, buf, (size_t)len) == len;
    int saved_errno = errno;
    close(fd);
    errno = saved_errno;
    return ok;
}

static bool process_name_is(pid_t pid, const char *expected) {
    char path[64];
    char cmdline[256];
    int n = snprintf(path, sizeof(path), "/proc/%d/cmdline", pid);
    if (n <= 0 || (size_t)n >= sizeof(path)) {
        return false;
    }
    if (!read_text(path, cmdline, sizeof(cmdline))) {
        return false;
    }
    return strcmp(cmdline, expected) == 0;
}

static pid_t find_process_by_name(const char *expected) {
    DIR *dir = opendir("/proc");
    if (dir == NULL) {
        return 0;
    }

    struct dirent *entry;
    pid_t found = 0;
    while ((entry = readdir(dir)) != NULL) {
        char *end = NULL;
        errno = 0;
        long parsed = strtol(entry->d_name, &end, 10);
        if (errno != 0 || end == entry->d_name || *end != '\0' || parsed <= 0 || parsed > 2147483647L) {
            continue;
        }
        pid_t pid = (pid_t)parsed;
        if (process_name_is(pid, expected)) {
            found = pid;
            break;
        }
    }
    closedir(dir);
    return found;
}

static bool run_mount_namespace_action(pid_t pid,
                                       const char *source,
                                       const char *target,
                                       bool bind_mount) {
    pid_t child = fork();
    if (child < 0) {
        return false;
    }
    if (child == 0) {
        char ns_path[64];
        int n = snprintf(ns_path, sizeof(ns_path), "/proc/%d/ns/mnt", pid);
        if (n <= 0 || (size_t)n >= sizeof(ns_path)) {
            _exit(100);
        }
        int ns_fd = open(ns_path, O_RDONLY | O_CLOEXEC);
        if (ns_fd < 0) {
            _exit(101);
        }
        if (setns(ns_fd, CLONE_NEWNS) != 0) {
            close(ns_fd);
            _exit(102);
        }
        close(ns_fd);

        if (bind_mount) {
            if (mount(source, target, NULL, MS_BIND, NULL) != 0) {
                _exit(103);
            }
        } else {
            if (umount2(target, MNT_DETACH) != 0 && errno != EINVAL && errno != ENOENT) {
                _exit(104);
            }
        }
        _exit(0);
    }

    int status = 0;
    while (waitpid(child, &status, 0) < 0) {
        if (errno != EINTR) {
            return false;
        }
    }
    return WIFEXITED(status) && WEXITSTATUS(status) == 0;
}

static bool mount_powerkeeper_filter(pid_t pid, const char *proxy_path, const char *target_path) {
    return run_mount_namespace_action(pid, proxy_path, target_path, true);
}

static bool unmount_powerkeeper_filter(pid_t pid, const char *target_path) {
    if (pid <= 0 || !process_name_is(pid, POWERKEEPER_PROCESS)) {
        return true;
    }
    return run_mount_namespace_action(pid, NULL, target_path, false);
}

static int filter_torch_state_digit(int raw_state) {
    if (raw_state <= 0) {
        return raw_state < 0 ? 0 : raw_state;
    }
    return raw_state - (raw_state % 10);
}

static bool find_flash_thermal(char *out, size_t size) {
    const char *override = getenv("HYPERTORCH_THERMAL_PATH");
    if (override != NULL && override[0] != '\0') {
        int n = snprintf(out, size, "%s", override);
        return n > 0 && (size_t)n < size;
    }

    DIR *dir = opendir("/sys/class/thermal");
    if (dir == NULL) {
        return false;
    }

    struct dirent *entry;
    bool found = false;
    while ((entry = readdir(dir)) != NULL) {
        if (strncmp(entry->d_name, "thermal_zone", 12) != 0) {
            continue;
        }
        char type_path[MAX_PATH_LEN];
        char type[128];
        int n = snprintf(type_path, sizeof(type_path), "/sys/class/thermal/%s/type", entry->d_name);
        if (n <= 0 || (size_t)n >= sizeof(type_path)) {
            continue;
        }
        if (!read_text(type_path, type, sizeof(type)) || strcmp(type, "flash_therm") != 0) {
            continue;
        }
        n = snprintf(out, size, "/sys/class/thermal/%s/temp", entry->d_name);
        if (n > 0 && (size_t)n < size) {
            found = true;
        }
        break;
    }
    closedir(dir);
    return found;
}

static int parse_poll_ms(void) {
    const char *value = getenv("HYPERTORCH_POLL_MS");
    if (value == NULL || value[0] == '\0') {
        return DEFAULT_POLL_MS;
    }
    char *end = NULL;
    long parsed = strtol(value, &end, 10);
    if (end == value || *end != '\0' || parsed < 20 || parsed > 5000) {
        return DEFAULT_POLL_MS;
    }
    return (int)parsed;
}

static const char *path_or_default(const char *env_name, const char *fallback) {
    const char *value = getenv(env_name);
    return (value != NULL && value[0] != '\0') ? value : fallback;
}

static void sleep_ms(int ms) {
    usleep((useconds_t)ms * 1000U);
}

int main(void) {
    signal(SIGTERM, on_signal);
    signal(SIGINT, on_signal);
    signal(SIGHUP, on_signal);

    const char *brightness_path = path_or_default(
            "HYPERTORCH_BRIGHTNESS_PATH", "/sys/class/leds/yellow:flash-0/brightness");
    const char *strobe_path = path_or_default(
            "HYPERTORCH_STROBE_PATH", "/sys/class/leds/yellow:flash-0/flash_strobe");
    const char *temp_state_path = path_or_default(
            "HYPERTORCH_TEMP_STATE_PATH", TEMP_STATE_PATH);
    const char *powerkeeper_target_path = path_or_default(
            "HYPERTORCH_POWERKEEPER_TEMP_STATE_TARGET", TEMP_STATE_PATH);
    const char *temp_state_proxy = getenv("HYPERTORCH_TEMP_STATE_PROXY");
    const char *disable_mask_value = getenv("HYPERTORCH_DISABLE_POWERKEEPER_MASK");
    const bool powerkeeper_mask_enabled =
            !(disable_mask_value != NULL && strcmp(disable_mask_value, "1") == 0);
    const int poll_ms = parse_poll_ms();

    if (powerkeeper_mask_enabled && (temp_state_proxy == NULL || temp_state_proxy[0] == '\0')) {
        __android_log_print(ANDROID_LOG_ERROR, LOG_TAG,
                            "PowerKeeper filter requested but HYPERTORCH_TEMP_STATE_PROXY is unset");
        return 2;
    }

    char thermal_path[MAX_PATH_LEN] = {0};
    bool throttled = false;
    int saved_target = 0;
    bool announced_ready = false;
    pid_t masked_powerkeeper_pid = 0;
    int last_proxy_value = -2147483647 - 1;
    int mask_retry_ticks = 0;

    while (g_running) {
        if (thermal_path[0] == '\0' && !find_flash_thermal(thermal_path, sizeof(thermal_path))) {
            sleep_ms(1000);
            continue;
        }

        if (!announced_ready) {
            __android_log_print(ANDROID_LOG_INFO, LOG_TAG,
                                "thermal governor ready: 80C clamp / 75C release, stock=%d, poll=%dms, thermal=%s",
                                STOCK_BRIGHTNESS, poll_ms, thermal_path);
            announced_ready = true;
        }

        int temp_mc = 0;
        int strobe = 0;
        int brightness = 0;
        int raw_temp_state = 0;
        if (!read_int(thermal_path, &temp_mc)) {
            thermal_path[0] = '\0';
            announced_ready = false;
            sleep_ms(1000);
            continue;
        }
        if (!read_int(strobe_path, &strobe) || !read_int(brightness_path, &brightness)) {
            sleep_ms(poll_ms);
            continue;
        }

        const bool torch_active = strobe > 0 && brightness > 0;

        if (powerkeeper_mask_enabled) {
            if (masked_powerkeeper_pid > 0 &&
                !process_name_is(masked_powerkeeper_pid, POWERKEEPER_PROCESS)) {
                masked_powerkeeper_pid = 0;
            }

            if (torch_active) {
                if (read_int(temp_state_path, &raw_temp_state)) {
                    const int filtered_state = filter_torch_state_digit(raw_temp_state);
                    if (filtered_state != last_proxy_value) {
                        if (write_int(temp_state_proxy, filtered_state)) {
                            last_proxy_value = filtered_state;
                        } else {
                            __android_log_print(ANDROID_LOG_ERROR, LOG_TAG,
                                                "cannot update PowerKeeper temp_state proxy: %s",
                                                strerror(errno));
                        }
                    }
                }

                if (masked_powerkeeper_pid == 0) {
                    if (mask_retry_ticks > 0) {
                        --mask_retry_ticks;
                    } else {
                        pid_t pid = find_process_by_name(POWERKEEPER_PROCESS);
                        if (pid > 0 && mount_powerkeeper_filter(pid, temp_state_proxy,
                                                                powerkeeper_target_path)) {
                            masked_powerkeeper_pid = pid;
                            __android_log_print(ANDROID_LOG_INFO, LOG_TAG,
                                                "PowerKeeper torch thermal policy masked in pid=%d namespace",
                                                pid);
                        } else {
                            __android_log_print(ANDROID_LOG_ERROR, LOG_TAG,
                                                "PowerKeeper namespace filter mount failed; retrying");
                            mask_retry_ticks = (1000 + poll_ms - 1) / poll_ms;
                        }
                    }
                }
            } else if (masked_powerkeeper_pid > 0) {
                pid_t pid = masked_powerkeeper_pid;
                if (unmount_powerkeeper_filter(pid, powerkeeper_target_path)) {
                    __android_log_print(ANDROID_LOG_INFO, LOG_TAG,
                                        "PowerKeeper torch thermal policy restored in pid=%d namespace",
                                        pid);
                } else {
                    __android_log_print(ANDROID_LOG_ERROR, LOG_TAG,
                                        "PowerKeeper namespace filter unmount failed for pid=%d",
                                        pid);
                }
                masked_powerkeeper_pid = 0;
                mask_retry_ticks = 0;
            }
        }

        if (!torch_active) {
            if (throttled) {
                __android_log_print(ANDROID_LOG_INFO, LOG_TAG,
                                    "thermal throttle cleared because torch session ended");
            }
            throttled = false;
            saved_target = 0;
            sleep_ms(poll_ms);
            continue;
        }

        if (!throttled) {
            if (temp_mc >= TRIP_ON_MC && brightness > STOCK_BRIGHTNESS) {
                saved_target = brightness;
                if (write_int(brightness_path, STOCK_BRIGHTNESS)) {
                    throttled = true;
                    __android_log_print(ANDROID_LOG_WARN, LOG_TAG,
                                        "thermal throttle ON: temp=%d mC target=%d -> %d",
                                        temp_mc, saved_target, STOCK_BRIGHTNESS);
                } else {
                    __android_log_print(ANDROID_LOG_ERROR, LOG_TAG,
                                        "thermal clamp write failed at temp=%d mC: %s",
                                        temp_mc, strerror(errno));
                }
            }
            sleep_ms(poll_ms);
            continue;
        }

        if (brightness > STOCK_BRIGHTNESS) {
            // HAL/SystemUI may receive a new slider target while hot. Remember the newest enhanced
            // target, then clamp it again. This is the only steady-state write path.
            saved_target = brightness;
            if (!write_int(brightness_path, STOCK_BRIGHTNESS)) {
                __android_log_print(ANDROID_LOG_ERROR, LOG_TAG,
                                    "thermal re-clamp write failed at temp=%d mC: %s",
                                    temp_mc, strerror(errno));
            }
        } else if (brightness < STOCK_BRIGHTNESS) {
            // If the user deliberately moves below the stock ceiling while throttled, do not
            // restore the earlier high value when the device cools.
            saved_target = brightness;
        }

        if (temp_mc <= TRIP_OFF_MC) {
            int restore = saved_target;
            if (restore > STOCK_BRIGHTNESS) {
                int current_strobe = 0;
                if (read_int(strobe_path, &current_strobe) && current_strobe > 0) {
                    if (!write_int(brightness_path, restore)) {
                        __android_log_print(ANDROID_LOG_ERROR, LOG_TAG,
                                            "thermal restore write failed at temp=%d mC: %s",
                                            temp_mc, strerror(errno));
                        sleep_ms(poll_ms);
                        continue;
                    }
                }
            }
            __android_log_print(ANDROID_LOG_INFO, LOG_TAG,
                                "thermal throttle OFF: temp=%d mC restore=%d",
                                temp_mc, restore);
            throttled = false;
            saved_target = 0;
        }

        sleep_ms(poll_ms);
    }

    if (powerkeeper_mask_enabled && masked_powerkeeper_pid > 0) {
        (void)unmount_powerkeeper_filter(masked_powerkeeper_pid, powerkeeper_target_path);
    }

    return 0;
}
