"""Read-only discovery fixtures and real native-governor state transitions."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


class Discovery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.device = 'pudding'
        self.pk = True
        self.boot_completed = True
        self.stub('getprop', 'case "$1" in ro.product.device) echo "${TEST_DEVICE}" ;; ro.soc.model) echo SM8850 ;; ro.build.fingerprint) echo fixture/build/1 ;; sys.boot_completed) echo "${TEST_BOOT}" ;; esac')
        self.stub('pm', '[ "$TEST_PK" = 1 ] && echo package:/system/PowerKeeper.apk')

    def tearDown(self):
        self.tmp.cleanup()

    def stub(self, name, code):
        p = self.bin / name
        p.write_text('#!/bin/sh\n' + code + '\n')
        p.chmod(0o755)

    def put(self, path, text):
        p = self.root / path.lstrip('/')
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(str(text))
        return p

    def led(self, name='yellow:flash-0', maximum=255, strobe=True):
        p = f'sys/class/leds/{name}'
        self.put(p + '/brightness', '0\n')
        self.put(p + '/max_brightness', f'{maximum}\n')
        if strobe:
            self.put(p + '/flash_strobe', '0\n')
        return self.root / p

    def hal(self, base='odm/etc/camera', text=None):
        return self.put(base + '/camxoverridesettings.txt', text or
                        '# untouched\nFlashTorchCurrentSwitch=TRUE\noverrideFlashTorchCurrent=150\nother=42\n')

    def sensor(self, name='flash_therm', zone=0, temp=30000):
        self.put(f'sys/class/thermal/thermal_zone{zone}/type', name)
        self.put(f'sys/class/thermal/thermal_zone{zone}/temp', str(temp))

    def full(self):
        self.led()
        self.hal()
        self.sensor()
        self.put('sys/class/thermal/thermal_message/temp_state', 123)

    def probe(self, module=None):
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        result = subprocess.run(['sh', str((module or ROOT) / 'probe.sh')], env={**os.environ,
            'PATH': str(self.bin) + os.pathsep + os.environ['PATH'],
            'HYPERTORCH_TEST_ROOT': str(self.root), 'TEST_DEVICE': self.device,
            'TEST_PK': '1' if self.pk else '0', 'TEST_BOOT': '1' if self.boot_completed else '0'}, text=True, capture_output=True, check=True)
        for p, data in before.items():
            self.assertEqual(data, p.read_bytes(), f'discovery changed {p}')
        fields = {}
        for line in result.stdout.splitlines():
            key, value = line.split('\t', 1)
            fields.setdefault(key, []).append(value)
        return {k: v[0] if len(v) == 1 else v for k, v in fields.items()}

    def test_calibrated_device(self):
        self.full()
        d = self.probe()
        self.assertEqual(d['mode'], 'calibrated')
        self.assertEqual(d['target_current_ma'], '500')

    def test_other_device_retains_stock(self):
        self.full(); self.device = 'haotian'
        d = self.probe()
        self.assertEqual(d['mode'], 'diagnostic')
        self.assertEqual(d['reason'], 'calibration_required')
        self.assertNotIn('target_current_ma', d)

    def test_dynamic_led_ranges(self):
        for maximum in [1, 31, 100, 1023, 4095]:
            with self.subTest(maximum=maximum):
                self.led('white:torch', maximum, False)
                d = self.probe()
                self.assertEqual(d['max_brightness'], str(maximum))
                self.assertEqual(d['led_kind'], 'dedicated_torch')

    def test_ambiguous_leds(self):
        self.full(); self.led('white:torch')
        self.assertEqual(self.probe()['reason'], 'led_missing_or_ambiguous')

    def test_calibrated_three_channel_topology(self):
        self.full(); self.led('white:flash-1'); self.led('amber:flash-2')
        d = self.probe()
        self.assertEqual(d['led_count'], '3')
        self.assertEqual(d['led_selection'], 'calibrated_profile')
        self.assertTrue(d['led'].endswith('yellow:flash-0'))
        self.assertEqual(d['mode'], 'calibrated')

    def test_unknown_three_channel_topology_stays_ambiguous(self):
        self.full(); self.led('white:flash-1'); self.led('amber:flash-2')
        self.device = 'haotian'
        self.assertEqual(self.probe()['reason'], 'led_missing_or_ambiguous')

    def test_unexpected_extra_channel_stays_ambiguous(self):
        self.full(); self.led('white:flash-1'); self.led('amber:flash-2'); self.led('rear:torch')
        self.assertEqual(self.probe()['reason'], 'led_missing_or_ambiguous')

    def test_shell_terminal_lines_variable_is_not_used(self):
        self.assertNotRegex((ROOT / 'lib/discovery.sh').read_text(), r'\bLINES=')

    def test_led_alias_dedup(self):
        self.full()
        (self.root / 'sys/class/leds/alias:torch').symlink_to('yellow:flash-0')
        d = self.probe()
        self.assertEqual(d['led_count'], '1')
        self.assertEqual(d['mode'], 'calibrated')

    def test_do_not_choose_notification_or_pulse_led(self):
        self.led('white:flash', strobe=False)
        self.led('red:indicator', strobe=False)
        self.assertEqual(self.probe()['led_count'], '0')

    def test_invalid_led_range(self):
        self.led(maximum=0)
        self.assertEqual(self.probe()['led_count'], '0')

    def test_vendor_and_nested_camx(self):
        for base in ['vendor/etc/camera', 'product/etc/camera/rear', 'odm/etc/camera/a/b']:
            with self.subTest(base=base):
                p = self.hal(base)
                self.assertEqual(self.probe()['hal'], str(p))
                p.unlink()

    def test_hal_alias_dedup(self):
        self.full()
        (self.root / 'vendor').symlink_to('odm')
        self.assertEqual(self.probe()['hal_count'], '1')

    def test_ambiguous_hal(self):
        self.full(); self.hal('vendor/etc/camera')
        self.assertEqual(self.probe()['reason'], 'hal_missing_or_ambiguous')

    def test_duplicate_hal_keys(self):
        self.full()
        self.hal(text='FlashTorchCurrentSwitch=TRUE\noverrideFlashTorchCurrent=150\noverrideFlashTorchCurrent=250\n')
        self.assertEqual(self.probe()['hal_count'], '0')

    def test_disabled_hal_switch(self):
        self.full(); self.hal(text='FlashTorchCurrentSwitch=FALSE\noverrideFlashTorchCurrent=150\n')
        self.assertEqual(self.probe()['hal_count'], '0')

    def test_whitespace_crlf_hal(self):
        self.full(); self.hal(text=' FlashTorchCurrentSwitch = TRUE\r\n overrideFlashTorchCurrent = 150\r\n')
        self.assertEqual(self.probe()['hal_count'], '1')

    def test_unknown_sensor_never_uses_cpu_temperature(self):
        self.led(); self.hal(); self.sensor('cpu-0')
        self.assertEqual(self.probe()['reason'], 'thermal_missing_or_ambiguous')

    def test_sensor_aliases(self):
        for name in ['flash-therm', 'torch_therm', 'torch-therm', 'flashlight_therm', 'led_therm']:
            with self.subTest(name=name):
                self.sensor(name)
                self.assertEqual(self.probe()['thermal_type'], name)

    def test_multiple_thermal_sensors(self):
        self.full(); self.sensor('torch_therm', 1)
        self.assertEqual(self.probe()['reason'], 'thermal_missing_or_ambiguous')

    def test_bad_thermal_units(self):
        self.full(); self.sensor(temp=35)
        self.assertEqual(self.probe()['thermal_count'], '0')

    def test_missing_powerkeeper(self):
        self.full(); self.pk = False
        self.assertEqual(self.probe()['mode'], 'diagnostic')

    def test_oem_current_changed(self):
        self.full(); self.hal(text='FlashTorchCurrentSwitch=TRUE\noverrideFlashTorchCurrent=250\n')
        self.assertEqual(self.probe()['mode'], 'diagnostic')

    def test_mtk_and_v4l_are_inventory_only(self):
        self.put('proc/driver/flashlight', 'OEM command ABI unknown')
        self.put('dev/v4l-subdev0', '')
        d = self.probe()
        self.assertEqual(len(d['vendor_candidate']), 2)
        self.assertEqual(d['mode'], 'diagnostic')

    def test_early_boot_without_package_manager(self):
        self.full(); self.boot_completed = False
        self.stub('pm', 'echo CALLED > "$HYPERTORCH_TEST_ROOT/pm_called"; exit 1')
        self.put('data/system/packages.list', 'com.miui.powerkeeper 1000 0 /data/user/0/com.miui.powerkeeper default 0\n')
        self.assertEqual(self.probe()['mode'], 'calibrated')
        self.assertFalse((self.root / 'pm_called').exists())

    def test_early_boot_does_not_query_binder(self):
        self.full(); self.boot_completed = False
        self.stub('pm', 'echo CALLED > "$HYPERTORCH_TEST_ROOT/pm_called"; exit 1')
        self.assertEqual(self.probe()['mode'], 'diagnostic')
        self.assertFalse((self.root / 'pm_called').exists())

    def test_thermal_alias_dedup(self):
        self.full()
        (self.root / 'sys/class/thermal/thermal_zone99').symlink_to('thermal_zone0')
        self.assertEqual(self.probe()['thermal_count'], '1')

    def module_copy(self):
        mod = self.root / 'module'
        mod.mkdir()
        for name in ['customize.sh', 'action.sh', 'probe.sh', 'native-probe.sh', 'post-fs-data.sh', 'module.prop', 'lib/discovery.sh']:
            dest = mod / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, dest)
        (mod / 'bin').mkdir()
        (mod / 'bin/thermal_governor').touch()
        return mod

    def test_unknown_device_installs_in_diagnostic_mode(self):
        self.full(); self.device = 'haotian'
        mod = self.module_copy()
        before = {p: p.read_bytes() for p in (self.root / 'sys').rglob('*') if p.is_file()}
        result = subprocess.run(['sh', '-c',
            'ui_print() { printf "%s\\n" "$*"; }; abort() { echo "$*"; exit 1; }; '
            'set_perm() { :; }; set_perm_recursive() { :; }; . "$MODPATH/customize.sh"'],
            env={**os.environ, 'PATH': str(self.bin) + os.pathsep + os.environ['PATH'],
                 'ARCH': 'arm64', 'MODPATH': str(mod), 'HYPERTORCH_TEST_ROOT': str(self.root),
                 'TEST_DEVICE': self.device, 'TEST_PK': '1', 'TEST_BOOT': '1'},
            text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('仅诊断', (mod / 'module.prop').read_text())
        self.assertEqual((mod / '.install-capabilities').stat().st_mode & 0o777, 0o600)
        for p, data in before.items():
            self.assertEqual(data, p.read_bytes())

    def test_action_keeps_boot_manifest_and_status(self):
        self.full(); mod = self.module_copy()
        (mod / '.runtime-capabilities').write_text('boot-only-manifest')
        (mod / '.hal-ready').write_text('boot-id')
        (mod / '.status').write_text('增强配置已加载')
        before = {p: p.read_bytes() for p in [mod / '.runtime-capabilities', mod / '.hal-ready', mod / '.status']}
        result = subprocess.run(['sh', str(mod / 'action.sh')], env={**os.environ,
            'PATH': str(self.bin) + os.pathsep + os.environ['PATH'],
            'HYPERTORCH_TEST_ROOT': str(self.root), 'TEST_DEVICE': self.device,
            'TEST_PK': '1', 'TEST_BOOT': '1'}, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        for p, data in before.items():
            self.assertEqual(data, p.read_bytes())
        self.assertEqual(list(mod.glob('.probe-report.*')), [])



class NativeProbeFlow(unittest.TestCase):
    def setUp(self):
        self.fixture = Discovery(methodName='test_calibrated_device')
        self.fixture.setUp()
        self.d = self.fixture
        self.d.full()
        self.d.device = 'haotian'
        self.mod = self.d.module_copy()
        (self.mod / 'bin/torch_probe.dex').write_bytes(b'dex fixture')

    def tearDown(self):
        self.d.tearDown()

    def env(self, **extra):
        return {**os.environ, 'PATH': str(self.d.bin) + os.pathsep + os.environ['PATH'],
                'HYPERTORCH_TEST_ROOT': str(self.d.root), 'TEST_DEVICE': self.d.device,
                'TEST_PK': '1', 'TEST_BOOT': '1' if self.d.boot_completed else '0',
                **extra}

    def run_native(self, **extra):
        report = self.mod / '.native-capabilities'
        p = subprocess.run(['sh', str(self.mod / 'native-probe.sh'), '--output', str(report)],
                           env=self.env(**extra), text=True, capture_output=True, timeout=18)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(report.stat().st_mode & 0o777, 0o600)
        self.assertEqual(list(self.mod.glob('.native-result.*')), [])
        return dict(line.split('\t', 1) for line in report.read_text().splitlines())

    def manifest(self, **changes):
        d = self.d.probe(self.mod)
        fields = {
            'native_format': '1', 'native_status': 'mapped_maximum',
            'native_device': self.d.device, 'native_soc': 'SM8850',
            'native_firmware': 'fixture/build/1',
            'native_led_topology': d['led_topology'],
            'native_api_verified': '1', 'native_off_verified': '1',
            'native_mapping_verified': '1', 'native_channel_count': '1',
            'native_driver_max': '255',
            'native_selected_led': str(self.d.root / 'sys/class/leds/yellow:flash-0'),
        }
        fields.update(changes)
        (self.mod / '.native-capabilities').write_text(
            ''.join(f'{k}\t{v}\n' for k, v in fields.items()))
        return fields

    def test_native_correlation_resolves_unknown_multichannel(self):
        self.d.led('white:flash-1'); self.d.led('amber:flash-2')
        self.manifest()
        d = self.d.probe(self.mod)
        self.assertEqual(d['led_selection'], 'native_api_correlation')
        self.assertEqual(d['native_cache_usable'], '1')
        self.assertEqual(d['mode'], 'diagnostic')
        self.assertEqual(d['reason'], 'calibration_required')
        self.assertNotIn('target_current_ma', d)

    def test_correlated_unnamed_led_can_be_selected(self):
        self.d.led('led0')
        self.manifest(native_selected_led=str(self.d.root / 'sys/class/leds/led0'))
        d = self.d.probe(self.mod)
        self.assertTrue(d['led'].endswith('/led0'))
        self.assertEqual(d['led_selection'], 'native_api_correlation')

    def test_firmware_change_invalidates_measured_mapping(self):
        self.d.led('white:flash-1')
        self.manifest(native_firmware='different/build')
        self.assertEqual(self.d.probe(self.mod)['native_cache_usable'], '0')

    def test_new_led_changes_topology_and_invalidates_cache(self):
        self.manifest()
        self.d.led('red:indicator')
        self.assertEqual(self.d.probe(self.mod)['native_cache_usable'], '0')

    def test_missing_off_confirmation_cannot_select(self):
        self.manifest(native_off_verified='0')
        self.assertEqual(self.d.probe(self.mod)['native_cache_usable'], '0')

    def test_group_of_two_channels_is_not_a_single_channel(self):
        self.manifest(native_channel_count='2')
        self.assertEqual(self.d.probe(self.mod)['native_cache_usable'], '0')

    def test_changed_driver_range_invalidates_cache(self):
        self.manifest(native_driver_max='1023')
        self.assertEqual(self.d.probe(self.mod)['native_cache_usable'], '0')

    def test_native_probe_user_disabled_does_not_launch_helper(self):
        self.d.stub('app_process', 'echo CALLED > "$HYPERTORCH_TEST_ROOT/called"; exit 1')
        d = self.run_native(HYPERTORCH_SKIP_NATIVE_PROBE='1')
        self.assertEqual(d['native_reason'], 'user_disabled')
        self.assertFalse((self.d.root / 'called').exists())

    def test_recovery_install_does_not_launch_helper(self):
        self.d.stub('app_process', 'exit 99')
        self.assertEqual(self.run_native(BOOTMODE='false')['native_reason'], 'recovery_install')

    def test_system_not_ready_skips_active_test(self):
        self.d.boot_completed = False
        self.assertEqual(self.run_native()['native_reason'], 'system_not_ready')

    def test_java_busy_report_is_retained(self):
        self.d.stub('app_process',
                    'printf "native_format\\t1\\nnative_status\\tskipped\\nnative_reason\\tcamera_busy\\n" > "$4"; exit 1')
        self.assertEqual(self.run_native()['native_reason'], 'camera_busy')

    def test_helper_crash_produces_explicit_report(self):
        self.d.stub('app_process', 'exit 9')
        self.assertEqual(self.run_native()['native_reason'], 'helper_failed')

    def test_readonly_action_never_runs_active_probe(self):
        self.d.stub('app_process', 'echo CALLED > "$HYPERTORCH_TEST_ROOT/called"')
        p = subprocess.run(['sh', str(self.mod / 'action.sh')], env=self.env(),
                           text=True, capture_output=True)
        self.assertEqual(p.returncode, 0)
        self.assertFalse((self.d.root / 'called').exists())

    def test_unknown_measured_device_still_does_not_mount_hal(self):
        self.manifest()
        before = {p: p.read_bytes() for p in (self.d.root / 'sys').rglob('*') if p.is_file()}
        p = subprocess.run(['sh', str(self.mod / 'post-fs-data.sh')], env=self.env(),
                           text=True, capture_output=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertFalse((self.mod / '.hal-ready').exists())
        for path, data in before.items():
            self.assertEqual(path.read_bytes(), data)

    def test_installer_uses_measured_channel_before_calibration_gate(self):
        self.d.led('white:flash-1')
        led = self.d.root / 'sys/class/leds/yellow:flash-0'
        helper = (
            'awk -F "\\t" \x27$1=="device" || $1=="soc" || $1=="firmware" || $1=="led_topology" '
            '{print "native_" $1 "\\t" $2}\x27 "$3" > "$4"\n'
            'printf "native_format\\t1\\nnative_status\\tmapped_maximum\\nnative_reason\\tsingle_correlated_led\\n'
            'native_api_verified\\t1\\nnative_off_verified\\t1\\nnative_mapping_verified\\t1\\n'
            'native_channel_count\\t1\\nnative_driver_max\\t255\\nnative_api_max_strength\\t100\\n'
            'native_observed_max\\t76\\nnative_selected_led\\t%s\\n" '
            f'\x27{led}\x27 >> "$4"\n')
        self.d.stub('app_process', helper)
        command = (
            'ui_print() { printf "%s\\n" "$*"; }; abort() { echo "$*"; exit 1; }; '
            'set_perm() { :; }; set_perm_recursive() { :; }; . "$MODPATH/customize.sh"')
        p = subprocess.run(['sh', '-c', command],
                           env=self.env(MODPATH=str(self.mod), ARCH='arm64', BOOTMODE='true'),
                           text=True, capture_output=True, timeout=5)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn('实测驱动值: 76', p.stdout)
        installed = (self.mod / '.install-capabilities').read_text()
        self.assertIn('led_selection\tnative_api_correlation', installed)
        self.assertIn('mode\tdiagnostic', installed)
        self.assertFalse((self.mod / '.hal-ready').exists())

    def test_cancelled_probe_kills_helper(self):
        marker = self.d.root / 'helper.pid'
        self.d.stub('app_process', 'echo ' + '$' * 2 + ' > "$HYPERTORCH_TEST_ROOT/helper.pid"; exec sleep 30')
        process = subprocess.Popen(
            ['sh', str(self.mod / 'native-probe.sh'), '--output', str(self.mod / '.native-capabilities')],
            env=self.env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 2
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertTrue(marker.exists())
            pid = int(marker.read_text())
            process.terminate()
            process.communicate(timeout=3)
            self.assertEqual(process.returncode, 130)
            self.assertFalse(Path(f'/proc/{pid}').exists())
        finally:
            if process.poll() is None:
                process.kill(); process.communicate(timeout=3)

    def test_timeout_is_bounded_and_reported(self):
        self.d.stub('app_process', 'exec sleep 30')
        start = time.monotonic()
        d = self.run_native()
        self.assertEqual(d['native_reason'], 'probe_timeout')
        self.assertLess(time.monotonic() - start, 16)

@unittest.skipUnless(os.name == 'posix' and shutil.which('gcc'), 'Linux gcc required')
class Governor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.TemporaryDirectory()
        shim = Path(cls.build.name) / 'android/log.h'
        shim.parent.mkdir()
        shim.write_text('#define ANDROID_LOG_ERROR 6\n#define ANDROID_LOG_WARN 5\n#define ANDROID_LOG_INFO 4\n'
                        'static inline int __android_log_print(int p, const char *tag, const char *f, ...)'
                        '{ (void)p; (void)tag; (void)f; return 0; }\n')
        cls.binary = Path(cls.build.name) / 'governor'
        subprocess.run(['gcc', '-Wall', '-Wextra', '-Werror', '-O2', '-I', cls.build.name,
                        str(ROOT / 'src/thermal_governor.c'), '-o', str(cls.binary)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.build.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        p = Path(self.tmp.name)
        self.brightness, self.strobe, self.temp = [p / n for n in ['brightness', 'strobe', 'temp']]
        self.write_value(self.brightness, '255'); self.strobe.write_text('1'); self.write_value(self.temp, '30000')
        self.env = {**os.environ, 'HYPERTORCH_BRIGHTNESS_PATH': str(self.brightness),
                    'HYPERTORCH_STROBE_PATH': str(self.strobe), 'HYPERTORCH_THERMAL_PATH': str(self.temp),
                    'HYPERTORCH_DISABLE_POWERKEEPER_MASK': '1', 'HYPERTORCH_POLL_MS': '20'}
        self.process = None

    def tearDown(self):
        if self.process is not None:
            self.process.terminate(); self.process.wait(timeout=3)
        self.tmp.cleanup()

    def write_value(self, path, value):
        temporary = path.with_name(path.name + '.next')
        temporary.write_text(str(value))
        os.replace(temporary, path)

    def start(self):
        self.process = subprocess.Popen([str(self.binary)], env=self.env)

    def expect(self, value, timeout=2):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.brightness.read_text().strip() == str(value):
                return
            time.sleep(.02)
        self.fail(f'expected brightness {value}; actual {self.brightness.read_text()}')

    def test_read_only_preflight(self):
        before = self.brightness.read_bytes()
        self.assertEqual(subprocess.run([str(self.binary), '--check'], env=self.env).returncode, 0)
        self.assertEqual(self.brightness.read_bytes(), before)

    def test_hysteresis_and_restore(self):
        self.write_value(self.temp, '81000'); self.start(); self.expect(76)
        self.write_value(self.temp, '77000'); time.sleep(.12); self.expect(76)
        self.write_value(self.temp, '74000'); self.expect(255)

    def test_user_lower_target_wins(self):
        self.write_value(self.temp, '81000'); self.start(); self.expect(76)
        self.write_value(self.brightness, '40'); time.sleep(.12)
        self.write_value(self.temp, '74000'); time.sleep(.12); self.expect(40)

    def test_kernel_off_is_never_reasserted(self):
        self.write_value(self.temp, '81000'); self.start(); self.expect(76)
        self.strobe.write_text('0'); self.write_value(self.brightness, '0'); time.sleep(.12)
        self.write_value(self.temp, '74000'); time.sleep(.12); self.expect(0)
        self.assertEqual(self.strobe.read_text(), '0')

    def test_sensor_loss_clamps_and_cancels_restore(self):
        self.start(); time.sleep(.1); self.write_value(self.temp, 'unavailable'); self.expect(76)
        self.write_value(self.temp, '30000'); time.sleep(1.2); self.expect(76)

    def test_non255_calibration(self):
        self.env.update(HYPERTORCH_MAX_BRIGHTNESS='1023', HYPERTORCH_STOCK_BRIGHTNESS='300',
                        HYPERTORCH_TRIP_ON_MC='70000', HYPERTORCH_TRIP_OFF_MC='60000')
        self.write_value(self.brightness, '1023'); self.write_value(self.temp, '71000'); self.start(); self.expect(300)
        self.write_value(self.temp, '59000'); self.expect(1023)

    def test_invalid_calibration_rejected(self):
        self.env['HYPERTORCH_TRIP_OFF_MC'] = '90000'
        self.assertEqual(subprocess.run([str(self.binary), '--check'], env=self.env).returncode, 2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
