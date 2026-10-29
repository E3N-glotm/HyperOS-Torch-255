import android.content.Context;
import android.hardware.camera2.CameraCharacteristics;
import android.hardware.camera2.CameraManager;
import android.os.Build;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.Looper;
import java.io.BufferedReader;
import java.io.File;
import java.io.FileReader;
import java.io.FileOutputStream;
import java.io.OutputStreamWriter;
import java.io.PrintWriter;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;

/** Installer-only active test. Hardware writes occur solely through CameraManager. */
public final class TorchProbe {
    private final Map<String, String> meta = new HashMap<>();
    private final List<TorchProbeCore.Channel> channels = new ArrayList<>();
    private final List<String[]> output = new ArrayList<>();
    private final AtomicBoolean finished = new AtomicBoolean(false);
    private CameraManager manager;
    private String camera;
    private boolean ownsTorch;
    private HandlerThread callbacks;
    private final Map<String, Boolean> available = new HashMap<>();
    private final Map<String, Boolean> torch = new HashMap<>();
    private CameraManager.AvailabilityCallback availabilityCallback;
    private CameraManager.TorchCallback torchCallback;
    private String reportPath;
    private boolean complete;

    private static String read(String path) {
        try (BufferedReader r = new BufferedReader(new FileReader(path))) {
            String line = r.readLine();
            return line == null ? "" : line.trim();
        } catch (Exception e) { return ""; }
    }

    private static int number(String path) {
        try {
            String text = read(path);
            if (!text.matches("[0-9]{1,7}")) return -2;
            return Integer.parseInt(text);
        } catch (Exception e) { return -2; }
    }

    private static String clean(String s) {
        return s == null ? "" : s.replace('\t', ' ').replace('\n', ' ').replace('\r', ' ');
    }

    private void emit(String key, Object value) { output.add(new String[]{key, clean(String.valueOf(value))}); }

    private void input(String path) throws Exception {
        Map<String, TorchProbeCore.Channel> unique = new LinkedHashMap<>();
        try (BufferedReader r = new BufferedReader(new FileReader(path))) {
            String line;
            while ((line = r.readLine()) != null) {
                String[] f = line.split("\t", 2);
                if (f.length != 2) continue;
                if (!"led_candidate".equals(f[0])) { meta.put(f[0], f[1]); continue; }
                String[] p = f[1].split("\\|", -1);
                if (p.length != 4 || !p[2].startsWith("max=") || !p[3].startsWith("strobe=")) continue;
                File led = new File(p[0]);
                String canonical = led.getCanonicalPath();
                if (!canonical.startsWith("/sys/") || canonical.contains("|")) continue;
                int maximum = Integer.parseInt(p[2].substring(4));
                if (maximum <= 0 || maximum > 1000000) continue;
                boolean strobe = !p[3].substring(7).isEmpty();
                unique.put(canonical, new TorchProbeCore.Channel(canonical, p[1], maximum, strobe));
                if (unique.size() > 64) throw new IllegalStateException("too_many_led_candidates");
            }
        }
        channels.addAll(unique.values());
    }

    private TorchProbeCore.Reading reading(TorchProbeCore.Channel c) {
        return new TorchProbeCore.Reading(number(c.path + "/brightness"),
            c.hasStrobe ? number(c.path + "/flash_strobe") : -1);
    }

    private void temperatureCheck() throws Exception {
        File[] zones = new File("/sys/class/thermal").listFiles();
        if (zones != null) for (File zone : zones) {
            if (!zone.getName().startsWith("thermal_zone")) continue;
            String type = read(zone + "/type").toLowerCase(java.util.Locale.ROOT);
            if (!type.matches("(flash|torch|flashlight|led)[_-]therm")) continue;
            int value = number(zone + "/temp");
            if (value >= 60000 && value <= 200000) throw new IllegalStateException("torch_temperature_high");
        }
        int battery = number("/sys/class/power_supply/battery/temp");
        if (battery >= 450 && battery <= 1000) throw new IllegalStateException("battery_temperature_high");
    }

    private void sample(String phase) throws Exception {
        for (int i = 0; i < 3; ++i) {
            temperatureCheck();
            for (TorchProbeCore.Channel c : channels) {
                TorchProbeCore.Reading r = reading(c);
                if ("before".equals(phase)) c.before.add(r);
                if ("low".equals(phase)) c.low.add(r);
                if ("high".equals(phase)) c.high.add(r);
                if ("after".equals(phase)) c.after.add(r);
            }
            Thread.sleep(100);
        }
    }

    private void setupCamera() throws Exception {
        Looper.prepareMainLooper();
        Class<?> activityThread = Class.forName("android.app.ActivityThread");
        Object thread = activityThread.getMethod("systemMain").invoke(null);
        Context context = (Context) activityThread.getMethod("getSystemContext").invoke(thread);
        manager = context.getSystemService(CameraManager.class);
        if (manager == null) throw new IllegalStateException("camera_service_unavailable");
        List<String> rear = new ArrayList<>();
        for (String id : manager.getCameraIdList()) {
            CameraCharacteristics c = manager.getCameraCharacteristics(id);
            Boolean flash = c.get(CameraCharacteristics.FLASH_INFO_AVAILABLE);
            Integer facing = c.get(CameraCharacteristics.LENS_FACING);
            if (Boolean.TRUE.equals(flash) && Integer.valueOf(CameraCharacteristics.LENS_FACING_BACK).equals(facing)) {
                rear.add(id);
                emit("native_camera_candidate", id);
            }
        }
        if (rear.contains("0")) camera = "0";
        else if (rear.size() == 1) camera = rear.get(0);
        else throw new IllegalStateException(rear.isEmpty() ? "rear_torch_unavailable" : "rear_camera_ambiguous");
        emit("native_camera", camera);
        callbacks = new HandlerThread("TorchProbeCallbacks");
        callbacks.start();
        Handler handler = new Handler(callbacks.getLooper());
        availabilityCallback = new CameraManager.AvailabilityCallback() {
            @Override public void onCameraAvailable(String id) {
                synchronized (available) { available.put(id, true); available.notifyAll(); }
            }
            @Override public void onCameraUnavailable(String id) {
                synchronized (available) { available.put(id, false); available.notifyAll(); }
            }
        };
        torchCallback = new CameraManager.TorchCallback() {
            @Override public void onTorchModeChanged(String id, boolean enabled) {
                synchronized (torch) { torch.put(id, enabled); torch.notifyAll(); }
            }
            @Override public void onTorchModeUnavailable(String id) {
                synchronized (torch) { torch.remove(id); torch.notifyAll(); }
            }
        };
        manager.registerAvailabilityCallback(availabilityCallback, handler);
        manager.registerTorchCallback(torchCallback, handler);
        long end = System.nanoTime() + 1200000000L;
        while (System.nanoTime() < end) {
            synchronized (available) {
                synchronized (torch) {
                    if (available.containsKey(camera) && torch.containsKey(camera)) break;
                }
            }
            Thread.sleep(25);
        }
        synchronized (available) {
            if (!Boolean.TRUE.equals(available.get(camera))) throw new IllegalStateException("camera_busy_or_unconfirmed");
        }
        synchronized (torch) {
            for (Boolean enabled : torch.values())
                if (Boolean.TRUE.equals(enabled)) throw new IllegalStateException("torch_already_on");
            if (!Boolean.FALSE.equals(torch.get(camera))) throw new IllegalStateException("torch_off_unconfirmed");
        }
        for (TorchProbeCore.Channel c : channels) {
            if ("unclassified_led".equals(c.kind)) continue;
            TorchProbeCore.Reading r = reading(c);
            if (r.brightness > 0 && r.strobe != 0) throw new IllegalStateException("led_already_on");
        }
    }

    private boolean awaitTorch(boolean enabled) throws InterruptedException {
        long end = System.nanoTime() + 700000000L;
        while (System.nanoTime() < end) {
            synchronized (torch) {
                if (Boolean.valueOf(enabled).equals(torch.get(camera))) return true;
            }
            Thread.sleep(20);
        }
        return false;
    }

    @SuppressWarnings("unchecked")
    private void runTest() throws Exception {
        setupCamera();
        temperatureCheck();
        sample("before");
        CameraCharacteristics c = manager.getCameraCharacteristics(camera);
        int maximum = -1;
        Method strength = null, getStrength = null;
        try { if (Build.VERSION.SDK_INT >= 33) {
            CameraCharacteristics.Key<Integer> key = (CameraCharacteristics.Key<Integer>)
                CameraCharacteristics.class.getField("FLASH_INFO_STRENGTH_MAXIMUM_LEVEL").get(null);
            Integer value = c.get(key);
            if (value != null && value > 0 && value <= 1000000) maximum = value;
            try {
                strength = CameraManager.class.getMethod("turnOnTorchWithStrengthLevel", String.class, int.class);
                getStrength = CameraManager.class.getMethod("getTorchStrengthLevel", String.class);
            } catch (NoSuchMethodException ignored) { maximum = -1; }
        } } catch (ReflectiveOperationException ignored) { maximum = -1; }
        final boolean adjustable = maximum > 0 && strength != null && getStrength != null;
        final boolean lowTested = adjustable && maximum > 1;
        emit("native_strength_mode", adjustable ? "maximum_level" : "default_only");
        emit("native_api_max_strength", adjustable ? String.valueOf(maximum) : "");
        try {
            if (lowTested) {
                strength.invoke(manager, camera, 1);
                ownsTorch = true;
                if (!awaitTorch(true)) throw new IllegalStateException("torch_on_unconfirmed");
                Thread.sleep(120);
                sample("low");
            }
            if (adjustable) strength.invoke(manager, camera, maximum);
            else manager.setTorchMode(camera, true);
            ownsTorch = true;
            if (!awaitTorch(true)) throw new IllegalStateException("torch_on_unconfirmed");
            if (adjustable && ((Integer) getStrength.invoke(manager, camera)).intValue() != maximum)
                throw new IllegalStateException("maximum_level_readback_mismatch");
            Thread.sleep(120);
            sample("high");
        } finally {
            if (ownsTorch) {
                manager.setTorchMode(camera, false);
                ownsTorch = false;
            }
        }
        if (!awaitTorch(false)) throw new IllegalStateException("torch_off_unconfirmed");
        Thread.sleep(120);
        sample("after");
        List<TorchProbeCore.Channel> found = TorchProbeCore.responsive(channels, lowTested);
        emit("native_api_verified", 1);
        emit("native_off_verified", 1);
        emit("native_maximum_verified", adjustable ? 1 : 0);
        emit("native_channel_count", found.size());
        for (TorchProbeCore.Channel channel : channels) {
            emit("native_channel_samples", channel.path + "|max=" + channel.maximum +
                "|before=" + channel.values(channel.before) + "|low=" + channel.values(channel.low) +
                "|high=" + channel.values(channel.high) + "|after=" + channel.values(channel.after));
        }
        for (TorchProbeCore.Channel channel : found)
            emit("native_responsive_led", channel.path + "|observed=" + channel.observedMaximum() +
                "|driver_max=" + channel.maximum + "|scaling=" + channel.scales());
        if (found.size() == 1) {
            TorchProbeCore.Channel channel = found.get(0);
            emit("native_selected_led", channel.path);
            emit("native_observed_max", adjustable ? String.valueOf(channel.observedMaximum()) : "");
            emit("native_observed_default", channel.observedMaximum());
            emit("native_driver_max", channel.maximum);
            emit("native_mapping_verified", 1);
            emit("native_status", adjustable ? "mapped_maximum" : "mapped_default");
            emit("native_reason", "single_correlated_led");
        } else {
            emit("native_status", found.isEmpty() ? "api_only" : "multi_channel");
            emit("native_reason", found.isEmpty() ? "no_readable_correlated_led" : "multiple_leds_respond_together");
        }
        complete = true;
    }

    private void save() throws Exception {
        File target = new File(reportPath);
        File tmp = new File(reportPath + ".java-tmp");
        try (PrintWriter writer = new PrintWriter(new OutputStreamWriter(
                new FileOutputStream(tmp), StandardCharsets.UTF_8))) {
            for (String[] f : output) writer.println(f[0] + "\t" + f[1]);
            if (writer.checkError()) throw new java.io.IOException("report_write_failed");
        }
        if (!tmp.renameTo(target)) throw new java.io.IOException("report_rename_failed");
    }

    public static void main(String[] args) {
        TorchProbe probe = new TorchProbe();
        int code = 1;
        try {
            if (args.length != 2) throw new IllegalArgumentException("inventory_and_output_required");
            probe.reportPath = args[1];
            probe.input(args[0]);
            probe.emit("native_format", 1);
            for (String key : new String[]{"device", "soc", "firmware", "led_topology", "environment"})
                probe.emit("native_" + key, probe.meta.getOrDefault(key, ""));
            probe.emit("native_timestamp_ms", System.currentTimeMillis());
            probe.emit("native_boot_id", read("/proc/sys/kernel/random/boot_id"));
            Thread deadline = new Thread(() -> {
                try { Thread.sleep(10000); } catch (InterruptedException ignored) { return; }
                if (!probe.finished.get()) Runtime.getRuntime().halt(124);
            }, "TorchProbeDeadline");
            deadline.setDaemon(true);
            deadline.start();
            probe.runTest();
            code = 0;
        } catch (Throwable failure) {
            probe.emit("native_status", "skipped");
            Throwable cause = failure.getCause() == null ? failure : failure.getCause();
            probe.emit("native_reason", cause.getClass().getSimpleName() + ":" + cause.getMessage());
        } finally {
            try {
                if (probe.ownsTorch && probe.manager != null && probe.camera != null)
                    probe.manager.setTorchMode(probe.camera, false);
            } catch (Throwable ignored) {}
            try {
                if (probe.manager != null && probe.availabilityCallback != null)
                    probe.manager.unregisterAvailabilityCallback(probe.availabilityCallback);
                if (probe.manager != null && probe.torchCallback != null)
                    probe.manager.unregisterTorchCallback(probe.torchCallback);
                if (probe.callbacks != null) probe.callbacks.quitSafely();
                if (probe.reportPath != null) probe.save();
            } catch (Throwable failure) { code = 1; }
            probe.finished.set(true);
        }
        System.exit(probe.complete ? code : 1);
    }
}
