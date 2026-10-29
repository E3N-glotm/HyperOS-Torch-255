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
        self.stub('getprop', 'case "$1" in ro.product.device) echo "${TEST_DEVICE}" ;; ro.soc.model) echo SM8850 ;; sys.boot_completed) echo "${TEST_BOOT}" ;; esac')
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

    def probe(self):
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        result = subprocess.run(['sh', str(ROOT / 'probe.sh')], env={**os.environ,
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
        for name in ['customize.sh', 'action.sh', 'probe.sh', 'module.prop', 'lib/discovery.sh']:
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
        self.brightness.write_text('255'); self.strobe.write_text('1'); self.temp.write_text('30000')
        self.env = {**os.environ, 'HYPERTORCH_BRIGHTNESS_PATH': str(self.brightness),
                    'HYPERTORCH_STROBE_PATH': str(self.strobe), 'HYPERTORCH_THERMAL_PATH': str(self.temp),
                    'HYPERTORCH_DISABLE_POWERKEEPER_MASK': '1', 'HYPERTORCH_POLL_MS': '20'}
        self.process = None

    def tearDown(self):
        if self.process is not None:
            self.process.terminate(); self.process.wait(timeout=3)
        self.tmp.cleanup()

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
        self.temp.write_text('81000'); self.start(); self.expect(76)
        self.temp.write_text('77000'); time.sleep(.12); self.expect(76)
        self.temp.write_text('74000'); self.expect(255)

    def test_user_lower_target_wins(self):
        self.temp.write_text('81000'); self.start(); self.expect(76)
        self.brightness.write_text('40'); time.sleep(.12)
        self.temp.write_text('74000'); time.sleep(.12); self.expect(40)

    def test_kernel_off_is_never_reasserted(self):
        self.temp.write_text('81000'); self.start(); self.expect(76)
        self.strobe.write_text('0'); self.brightness.write_text('0'); time.sleep(.12)
        self.temp.write_text('74000'); time.sleep(.12); self.expect(0)
        self.assertEqual(self.strobe.read_text(), '0')

    def test_sensor_loss_clamps_and_cancels_restore(self):
        self.start(); time.sleep(.1); self.temp.write_text('unavailable'); self.expect(76)
        self.temp.write_text('30000'); time.sleep(1.2); self.expect(76)

    def test_non255_calibration(self):
        self.env.update(HYPERTORCH_MAX_BRIGHTNESS='1023', HYPERTORCH_STOCK_BRIGHTNESS='300',
                        HYPERTORCH_TRIP_ON_MC='70000', HYPERTORCH_TRIP_OFF_MC='60000')
        self.brightness.write_text('1023'); self.temp.write_text('71000'); self.start(); self.expect(300)
        self.temp.write_text('59000'); self.expect(1023)

    def test_invalid_calibration_rejected(self):
        self.env['HYPERTORCH_TRIP_OFF_MC'] = '90000'
        self.assertEqual(subprocess.run([str(self.binary), '--check'], env=self.env).returncode, 2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
