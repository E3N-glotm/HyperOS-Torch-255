import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

public final class TorchProbeCoreTest {
    private static int passed;
    private static TorchProbeCore.Channel channel(String path, int maximum, boolean strobe) {
        return new TorchProbeCore.Channel(path, "unclassified_led", maximum, strobe);
    }
    private static void add(List<TorchProbeCore.Reading> list, int value, int strobe) {
        for (int i = 0; i < 3; ++i) list.add(new TorchProbeCore.Reading(value, strobe));
    }
    private static TorchProbeCore.Channel normal(String path, int maximum, int low, int high, boolean strobe) {
        TorchProbeCore.Channel c = channel(path, maximum, strobe);
        add(c.before, 0, strobe ? 0 : -1);
        add(c.low, low, strobe ? 1 : -1);
        add(c.high, high, strobe ? 1 : -1);
        add(c.after, 0, strobe ? 0 : -1);
        return c;
    }
    private static void check(boolean condition, String name) {
        if (!condition) throw new AssertionError(name);
        ++passed;
        System.out.println("PASS " + name);
    }
    public static void main(String[] args) {
        TorchProbeCore.Channel a = normal("/sys/led0", 1023, 20, 400, true);
        check(a.responds(true) && a.scales() && a.observedMaximum() == 400, "actual maximum differs from driver range");
        TorchProbeCore.Channel b = normal("/sys/unnamed", 31, 2, 25, false);
        check(b.responds(true), "unknown name and no strobe can correlate");
        TorchProbeCore.Channel quantized = normal("/sys/quantized", 255, 0, 40, true);
        check(quantized.responds(true), "lowest API level may quantize to zero or use another color channel");
        TorchProbeCore.Channel indicator = normal("/sys/red", 255, 0, 0, false);
        check(!indicator.responds(true), "unchanged notification LED rejected");
        TorchProbeCore.Channel noisy = normal("/sys/noisy", 255, 1, 100, true);
        noisy.high.set(1, new TorchProbeCore.Reading(99, 1));
        check(!noisy.responds(true), "unstable highest stage rejected");
        TorchProbeCore.Channel stayedOn = normal("/sys/stuck", 255, 1, 100, true);
        stayedOn.after.set(0, new TorchProbeCore.Reading(100, 1));
        check(!stayedOn.responds(true), "missing switch-off confirmation rejected");
        TorchProbeCore.Channel invalid = normal("/sys/invalid", 100, 2, 101, true);
        check(!invalid.responds(true), "out-of-range driver reading rejected");
        TorchProbeCore.Channel reverse = normal("/sys/reverse", 255, 120, 100, true);
        check(!reverse.responds(true), "inverse strength response rejected");
        TorchProbeCore.Channel fixed = normal("/sys/fixed", 255, 255, 255, true);
        check(fixed.responds(true) && !fixed.scales(), "fixed brightness with verified strobe is only a correlated observer");
        TorchProbeCore.Channel retained = normal("/sys/retained", 255, 20, 100, true);
        retained.before.clear(); retained.after.clear();
        add(retained.before, 70, 0); add(retained.after, 100, 0);
        check(retained.responds(true), "off state may retain brightness when strobe is zero");
        TorchProbeCore.Channel defaultOnly = normal("/sys/old", 31, 0, 20, false);
        defaultOnly.low.clear();
        check(defaultOnly.responds(false) && !defaultOnly.responds(true), "old API maps default without inventing maximum");
        List<TorchProbeCore.Channel> group = TorchProbeCore.responsive(Arrays.asList(a, b, indicator), true);
        check(group.size() == 2, "multiple real channels remain a group");
        a.high.remove(0);
        check(!a.responds(true), "incomplete sampling rejected");
        System.out.println("TorchProbeCore: " + passed + " checks passed");
    }
}
