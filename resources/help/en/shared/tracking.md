### Tacho Tracking Engine

Decides **where** in the record the analysis blocks are centred ([Spectrogram](topic:spectrogram/intro), [Order Tracking](topic:order_tracking/intro), [Overall Level](topic:overall_level/intro)). The settings below are described one by one: what each does and what it changes in the results.

**Defaults:** Step 50 RPM (0.05 s in time mode), Ramp Up.

## Mode

- **Free Run (Time):** a trigger every *Step* seconds from the start of the record. Ignores RPM. The X axis of the result is time and no tacho is needed.
- **RPM Tracked:** a trigger where the speed crosses a target RPM. The targets are whole multiples of the step ($0, 50, 100, \dots$), not offset by where a particular recording starts, so two runs can be compared point by point. The crossing is placed by linear interpolation between two samples. Needs a tacho channel. The X axis of the result is speed.

![Triggers of Free Run and RPM Tracked](tracking_triggers.png)

The same run-up and run-down, cut two ways. **Free Run** (left) places a trigger every second, whatever the speed: the points are evenly spaced in time but unevenly in rpm, and some fall in the standstill. **RPM Tracked** (right, Ramp Up) places one trigger each time the speed crosses a multiple of the step on the way up, so the points are evenly spaced in rpm and the run-down and the standstill are left out.

## Step

The distance between triggers: seconds in Free Run, rpm in RPM Tracked. It sets how many blocks are cut and how far apart. A small step gives more points and a longer calculation, and neighbouring blocks overlap, so neighbouring points are not independent. A large step gives fewer points, with gaps between the blocks: a narrow peak or a fast change between two triggers is not seen. The block length stays $N$; the frequency resolution is set by [FFT size](topic:shared/fft_size), not by the step.

![The same order curve cut with Step = 50 rpm and Step = 400 rpm](tracking_step.png)

The same run-up, order 2, with a narrow resonance at 3500 rpm. With Step = 50 rpm the peak is caught; with Step = 400 rpm no block falls on it and the curve passes it as if it were not there.

**A low step does not sharpen the result.** The speed keeps changing during a block, so one block covers a stretch of speed (here 100 rpm), and every point is an average over that stretch, whatever the step. Lowering the step below the stretch only adds points that overlap: the curve looks more detailed than it is, and the rpm axis seems to promise a resolution the data does not have.

![A narrow resonance cut with Step = 50 rpm and Step = 5 rpm](tracking_step_fine.png)

The same measurement with a fast run-up (125 rpm/s) and a resonance only 15 rpm wide. Step = 50 rpm and Step = 5 rpm give the same wide, lower peak, because one block covers 100 rpm, much more than the resonance. A slower run-up or a shorter block ([FFT size](topic:shared/fft_size), at the price of frequency resolution) narrows the stretch; a lower step does not.

## Ramp

Up counts only upward crossings, Down only downward ones. The standstill noise before a run-up and after a run-down is excluded. The same machine behaves differently when it speeds up and when it slows down, so Up and Down give different curves at the same speeds.

![Which part of a record Ramp Up and Ramp Down use](tracking_sweep.png)

The ramp works from the **highest point of the record**. **Up** takes the rise to that point, starting from the last moment the speed was at rest before it (or from the start of the record if it never was). **Down** takes the fall from that point to the first moment at rest after it (or to the end of the record). Only inside that stretch are the crossings of the targets looked for. A smaller run-up or run-down elsewhere in the record is not used: otherwise some speeds would be crossed twice.

Edge cases:

- A record with only a run-down gives no triggers for Ramp Up, and one with only a run-up gives none for Ramp Down.
- If a run-down comes first and a higher run-up later, Ramp Down finds nothing: the highest point is at the end, and the earlier run-down lies before it.
- A tacho that never reaches 0 (an idle at 800 rpm, say) is not trimmed: Up starts from the first sample, and the triggers begin at the first target at or above the lowest speed.

## Tracking range

**Min [RPM]** and **Max [RPM]**, next to the step, narrow the ramp to the speeds you care about. Empty fields mean auto: 0 rpm and the record's top speed, exactly the ramp described above. In Free Run the same fields are **Start [s]** and **End [s]** (see below).

- **Up** starts at the **last moment the speed is at or below Min** before the top speed of the record, and ends at the top speed. A short spin-up past Min and back before the real run is therefore not taken for the run, and the standstill and the wobbly start below Min give no blocks.
- **Down** is the mirror: it starts at the top speed and ends at the first moment at or below Min after it.
- Targets above **Max** are dropped. Max below the top speed does not pick an earlier run: the ramp is still found around the top speed of the whole record.
- The targets stay on **whole multiples of the step**: Min 1 030 rpm with Step 50 rpm gives a first point at 1 050 rpm, so two measurements analysed with different ranges still share speed points.
- A record that already starts above Min is used from its start.
- A reverse-rotation run takes the range in positive rpm, like its result axis.
- A Min at or above Max is refused as you enter it. A range the measurement never reaches (Min 40 000 rpm on a run to 35 000 rpm) stops with a message naming the measurement. In a [batch](topic:batch/intro) that measurement is listed as a problem and the other measurements still finish.
- The Spectrogram, Order Tracking and Overall Level tabs each keep their own range. **Calculate & Save Data** uses the tab's range, and a [workflow](topic:workflow/intro) block has it as *Rpm Min* / *Rpm Max* in its Properties (empty = auto). The Overall Level + Residual curves of Order Tracking use the orders' range.

### Start and End in Free Run

In Free Run the two fields read **Start [s]** and **End [s]** and narrow the record in time. Empty fields mean the whole record, exactly the blocks without a range.

- The times are the ones on the **time axis**, as in the time signal graph: a record that starts at 12.3 s analysed from 15 s starts 2.7 s into it.
- The **first block sits exactly on Start**, then one every step; the last one is at or before End. Unlike the rpm targets, the time grid is not on multiples of the step: Start 12.3 s with Step 0.5 s gives 12.3, 12.8, 13.3 s ... A Start before the record keeps its grid: Start 10 s with Step 0.5 s on a record from 12.3 s gives a first block at 12.5 s.
- The time range and the rpm range are remembered separately: switching the Tracking Mode shows the range of that mode, so an rpm value is never read as seconds. Each tab keeps its own pair, and a [workflow](topic:workflow/intro) block has it as *Time Start* / *Time End*.
- A Start at or after End is refused as you enter it. A range outside the record (Start 40 s on a record that ends at 30 s) stops with a message naming the measurement; in a batch the other measurements still finish.

## One block per speed: the first crossing

Each target speed gets exactly one block, from the **first time** the speed reaches it in the ramp direction. A later crossing of the same speed is ignored. The rpm axis of the result therefore has every speed once, evenly spaced.

![A wobbling and a sagging plateau: one trigger per speed](tracking_first_crossing.png)

Two run-ups with a plateau at 300 rpm, Step = 50 rpm. On the left the speed wobbles around the target: it crosses 300 rpm four times, but only the first crossing gives a block. On the right the plateau sags below its setpoint and the next ramp crosses 300 rpm again; that block is not repeated either. The same holds for a run-up that dips and recovers in the middle: the speeds it passes again keep the blocks from before the dip. Ramp Down is the mirror: the first time the speed falls to each target.

## Tacho cleaning

The tacho is cleaned first: samples steeper than 200 000 RPM/s and non-finite samples are replaced by interpolation, then a 50 ms moving average is applied. A negative-reading tacho is flipped, and negative speeds are clamped to 0. The tacho itself is a [raw signal](topic:raw_data/intro) channel that is never DC-corrected.

The average smooths the speed, so the speed read at a trigger is the smoothed one; a change faster than 50 ms is blurred.

![What the 50 ms moving average does to a short dip and to a step](tracking_cleaning.png)

Two fast events in the raw tacho (grey) and the cleaned speed the triggers use (blue). The averaging removes the noise, but it also spreads a change over the 50 ms window. A step of 200 rpm in 5 ms becomes a ramp 50 ms long. A dip 30 ms long, 200 rpm deep, becomes shallower (here about 140 rpm) and wider. A slow run-up or run-down is not affected: the average of a straight ramp is the same ramp.
