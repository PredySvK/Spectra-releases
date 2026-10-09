### Tacho Tracking Engine

Decides **where** in the record the analysis blocks are centred ([Spectrogram](topic:spectrogram/intro), [Order Tracking](topic:order_tracking/intro), [Overall Level](topic:overall_level/intro)). The settings below are described one by one: what each does and what it changes in the results.

**Defaults:** Step 50 RPM (0.05 s in time mode), Sweep Up, Hysteresis 10 RPM.

## Mode

- **Free Run (Time):** a trigger every *Step* seconds from the start of the record. Ignores RPM. The X axis of the result is time and no tacho is needed.
- **RPM Tracked:** a trigger where the speed crosses a target RPM. The targets are whole multiples of the step ($0, 50, 100, \dots$), not offset by where a particular recording starts, so two runs can be compared point by point. The crossing is placed by linear interpolation between two samples. Needs a tacho channel. The X axis of the result is speed.

![Triggers of Free Run and RPM Tracked](tracking_triggers.png)

The same run-up and run-down, cut two ways. **Free Run** (left) places a trigger every second, whatever the speed: the points are evenly spaced in time but unevenly in rpm, and some fall in the standstill. **RPM Tracked** (right, Sweep Up) places one trigger each time the speed crosses a multiple of the step on the way up, so the points are evenly spaced in rpm and the run-down and the standstill are left out.

## Step

The distance between triggers: seconds in Free Run, rpm in RPM Tracked. It sets how many blocks are cut and how far apart. A small step gives more points and a longer calculation, and neighbouring blocks overlap, so neighbouring points are not independent. A large step gives fewer points, with gaps between the blocks: a narrow peak or a fast change between two triggers is not seen. The block length stays $N$; the frequency resolution is set by [FFT size](topic:shared/fft_size), not by the step.

![The same order curve cut with Step = 50 rpm and Step = 400 rpm](tracking_step.png)

The same run-up, order 2, with a narrow resonance at 3500 rpm. With Step = 50 rpm the peak is caught; with Step = 400 rpm no block falls on it and the curve passes it as if it were not there.

**A low step does not sharpen the result.** The speed keeps changing during a block, so one block covers a stretch of speed (here 100 rpm), and every point is an average over that stretch, whatever the step. Lowering the step below the stretch only adds points that overlap: the curve looks more detailed than it is, and the rpm axis seems to promise a resolution the data does not have.

![A narrow resonance cut with Step = 50 rpm and Step = 5 rpm](tracking_step_fine.png)

The same measurement with a fast run-up (125 rpm/s) and a resonance only 15 rpm wide. Step = 50 rpm and Step = 5 rpm give the same wide, lower peak, because one block covers 100 rpm, much more than the resonance. A slower run-up or a shorter block ([FFT size](topic:shared/fft_size), at the price of frequency resolution) narrows the stretch; a lower step does not.

## Sweep

Up counts only upward crossings, Down only downward ones. The standstill noise before a run-up and after a run-down is excluded. The same machine behaves differently when it speeds up and when it slows down, so Up and Down give different curves at the same speeds.

![Which part of a record Sweep Up and Sweep Down use](tracking_sweep.png)

The sweep works from the **highest point of the record**. **Up** takes the rise to that point, starting from the last moment the speed was at rest before it (or from the start of the record if it never was). **Down** takes the fall from that point to the first moment at rest after it (or to the end of the record). Only inside that stretch are the crossings of the targets looked for. A smaller run-up or run-down elsewhere in the record is not used: otherwise some speeds would be crossed twice.

Edge cases:

- A record with only a run-down gives no triggers for Sweep Up, and one with only a run-up gives none for Sweep Down.
- If a run-down comes first and a higher run-up later, Sweep Down finds nothing: the highest point is at the end, and the earlier run-down lies before it.
- A tacho that never reaches 0 (an idle at 800 rpm, say) is not trimmed: Up starts from the first sample, and the triggers begin at the first target at or above the lowest speed.

## Hysteresis

Guards against a speed that dithers around a target. After a trigger at a target, the next trigger at the *same* target is accepted only once the speed has left the band around it on the far side. For an Up sweep that means dropping below target − hysteresis. Example: with 10 RPM, a trigger at 1000 RPM is not repeated until the speed has gone below 990 RPM and crossed 1000 again.

With a speed that wobbles around a target, too small a value gives several blocks at almost the same speed, which shows as duplicated points and a jagged curve. A larger value keeps one. Too large a value also drops a real dip and return that is smaller than it.

![The same wobbling speed with Hysteresis = 2 rpm and 10 rpm](tracking_hysteresis.png)

The speed wobbles by ±7 rpm around a target of 300 rpm. With Hysteresis = 2 rpm every wobble dips below the orange line (target − hysteresis) and comes back, so each return counts again: five triggers at almost the same speed. With Hysteresis = 10 rpm the speed never drops below 290 rpm, so the first trigger stands and the returns (hollow circles) are rejected: one trigger, one block.

## Tacho cleaning

The tacho is cleaned first: samples steeper than 200 000 RPM/s and non-finite samples are replaced by interpolation, then a 50 ms moving average is applied. A negative-reading tacho is flipped, and negative speeds are clamped to 0. The tacho itself is a [raw signal](topic:raw_data/intro) channel that is never DC-corrected.

The average smooths the speed, so the speed read at a trigger is the smoothed one; a change faster than 50 ms is blurred.

![What the 50 ms moving average does to a short dip and to a step](tracking_cleaning.png)

Two fast events in the raw tacho (grey) and the cleaned speed the triggers use (blue). The averaging removes the noise, but it also spreads a change over the 50 ms window. A step of 200 rpm in 5 ms becomes a ramp 50 ms long. A dip 30 ms long, 200 rpm deep, becomes shallower (here about 140 rpm) and wider. A slow run-up or run-down is not affected: the average of a straight ramp is the same ramp.
