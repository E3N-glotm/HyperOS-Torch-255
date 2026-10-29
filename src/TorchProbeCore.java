import java.util.ArrayList;
import java.util.List;

/** Correlates read-only LED samples with an OEM Camera API off/low/max/off sequence. */
public final class TorchProbeCore {
    public static final class Reading {
        public final int brightness;
        public final int strobe; // -1: no separate strobe control
        public Reading(int brightness, int strobe) {
            this.brightness = brightness;
            this.strobe = strobe;
        }
        boolean valid(int maximum) {
            return brightness >= 0 && brightness <= maximum && strobe >= -1 && strobe <= 1;
        }
        boolean off(int maximum) {
            return valid(maximum) && (strobe == 0 || (strobe == -1 && brightness == 0));
        }
        boolean on(int maximum) {
            return valid(maximum) && brightness > 0 && strobe != 0;
        }
    }

    public static final class Channel {
        public final String path;
        public final String kind;
        public final int maximum;
        public final boolean hasStrobe;
        public final List<Reading> before = new ArrayList<>();
        public final List<Reading> low = new ArrayList<>();
        public final List<Reading> high = new ArrayList<>();
        public final List<Reading> after = new ArrayList<>();
        public Channel(String path, String kind, int maximum, boolean hasStrobe) {
            this.path = path;
            this.kind = kind;
            this.maximum = maximum;
            this.hasStrobe = hasStrobe;
        }
        private boolean allOff(List<Reading> readings) {
            if (readings.size() < 3) return false;
            for (Reading r : readings) if (!r.off(maximum)) return false;
            return true;
        }
        private int stableOn(List<Reading> readings) {
            if (readings.size() < 3) return -1;
            int value = readings.get(0).brightness;
            for (Reading r : readings)
                if (!r.on(maximum) || r.brightness != value) return -1;
            return value;
        }
        private int stableLow() {
            if (low.size() < 3) return -1;
            int value = low.get(0).brightness;
            for (Reading r : low)
                if (!r.valid(maximum) || r.brightness != value) return -1;
            return value;
        }
        public boolean responds(boolean lowWasTested) {
            int highValue = stableOn(high);
            return maximum > 0 && maximum <= 1000000 && allOff(before) && allOff(after) &&
                highValue > 0 && (!lowWasTested ||
                    (stableLow() >= 0 && highValue >= stableLow()));
        }
        public boolean scales() { return stableLow() >= 0 && stableOn(high) > stableLow(); }
        public int observedMaximum() { return stableOn(high); }
        public String values(List<Reading> readings) {
            StringBuilder out = new StringBuilder();
            for (Reading r : readings) {
                if (out.length() > 0) out.append(',');
                out.append(r.brightness).append('/').append(r.strobe);
            }
            return out.toString();
        }
    }

    public static List<Channel> responsive(List<Channel> channels, boolean lowWasTested) {
        List<Channel> result = new ArrayList<>();
        for (Channel c : channels) if (c.responds(lowWasTested)) result.add(c);
        return result;
    }

    private TorchProbeCore() {}
}
