# Generate a signal

**Generate Debug Signal** creates a synthetic, multi-channel time signal for testing import and analysis. You set the speed profile and add signal components to each channel, inspect the active channel in the preview, then export the record as a Siemens Testlab ASC file ([Supported formats](topic:import/formats)).

## Open the generator

On the **Project** tab, choose **Generate Debug Signal** in the *Tools* group.

![The Signal Generator dialog](signal_generator.en.png)

## Set duration, sampling, and seed

| Setting | Default | Allowed range | What it controls |
|---|---:|---:|---|
| **Duration [s]** | 30 s | 0.1–1000 s, in 0.01 s steps | Record length. The generated sample count is the integer part of duration × sampling rate. |
| **Sampling [Hz]** | 10,000 Hz | 100–102,400 Hz, integer steps | Sample rate for every channel and the tacho. Frequencies above half this rate can alias. |
| **Seed** | blank (`random`) | 0–2,147,483,647 | Random-number seed for noise and tacho noise. Enter a fixed value to reproduce the same generated record from the same settings. |

With Seed blank, a new seed is drawn when you export (always within the allowed range); the success message records it, and entering it in Seed reproduces the export with the same settings. The live preview uses its own fixed noise seed, so its noise does not change to match the export seed. The generator settings start fresh when you reopen the dialog; **Load Preset…** loads a predefined starting configuration. The dialog remembers its window size and position.

## Shape the speed profile

**Tacho Settings** defines the clean rotational-speed profile used to synthesize [order](topic:order_tracking/orders) components. **Start** defaults to 0 RPM and **Stop** to 35,000 RPM; both accept 0–100,000 RPM. **Direction** offers:

| Direction | Profile |
|---|---|
| **Ramp Up** | Rises from Start to Stop. |
| **Ramp Down** | Falls from Stop to Start. |
| **Ramp Up & Down** | Uses the first half of the record to rise from Start to Stop and the second half to return to Start. |

![Tacho settings with plateaus and tacho noise](signal_generator_tacho.en.png)

The default profile is a straight ramp. Select **Enable Plateaus** to divide each ramp into **Steps** (1–50, default 3). **Plateau Ratio** (0.01–0.99, default 0.5) is the fraction of each step spent holding its new speed; the rest is the transition to that speed. For example, 0.5 gives each step equal time for the ramp and the hold. The step and ratio controls are available only while plateaus are enabled.

## Add components to a channel

Choose a component type, enter its values, and press **Add Component**. Components in a channel are added together. **Amp** is the base peak value for the sine-shaped **Order**, **Sine signal**, and **Chirp** components. For noise components, Amp sets the output standard deviation. Values use the channel's selected [unit](topic:units/intro).

| Type | **Value** | **Amp** and additional fields |
|---|---|---|
| **Order** | Order, from 0 to 100,000 | A sine wave whose frequency follows RPM: order × RPM / 60. **Amp End** can make its amplitude rise or fall linearly across the record. **Mod Ord** and **Mod Dep** add amplitude modulation and sidebands. **Res Hz** and **Amplif** add a speed-dependent resonance envelope as the order passes the resonance frequency. |
| **Sine signal** | Fixed frequency in Hz, from 0 to 100,000 | A fixed-frequency sine wave, independent of RPM. **Amp End** changes its amplitude linearly across the record. **Mod Ord** is the modulation frequency in Hz; **Mod Dep** is its depth from 0 to 1. |
| **Chirp** | Start frequency in Hz, from 0 to 100,000 | A linear frequency sweep from **Value** to **End Freq [Hz]** over the record, independent of RPM. **Amp End** and modulation work as for a fixed sine signal. Amplification is not available for Chirp. |
| **White Noise** | — | Gaussian white noise; Amp is its standard deviation. |
| **Pink Noise** | — | Noise weighted toward lower frequencies with equal energy per octave; Amp is its standard deviation. |
| **Brown Noise** | — | Noise weighted more strongly toward lower frequencies than pink noise; Amp is its standard deviation. |
| **Resonance** | — | Broadband noise shaped around **Res Freq [Hz]**. Amp sets its standard deviation; **Q factor** controls the sharpness of the resonance (values below 1 behave as 1). |

When adding a component through the controls above the table, the spin boxes limit **Value** to 0–100,000 (default 1), **Amp** and **Amp End** to 0–1,000,000 (both default 1), **Mod Ord** to 0–100,000 (default 0), **Mod Dep** to 0–1 (default 0), resonance or end frequency to 0–100,000 Hz (default 0), and **Amplification** or **Q factor** to 0–100 (default 1). These limits apply to the spin boxes; the table cells can also be edited directly. The visible fields depend on the component type. For Order, **Res Hz** is the resonance frequency in Hz and **Amplif** controls the resonance envelope; an envelope is applied only when the frequency is above 0 and Amplif is greater than 1. For Chirp, the frequency field is repurposed as its end frequency. When a component has **Amp End**, changing **Amp** before adding it also updates Amp End until you edit Amp End directly. Modulation is added only when both Mod Ord and Mod Dep are greater than zero; its depth multiplies the base amplitude between 1 − depth and 1 + depth.

## Preview a channel

The **Tacho Profile** plot shows speed against time. **Active Channel Vibration Preview** shows the selected channel only; switch channel tabs to preview another one. Its vertical unit follows that channel's unit. **X-Axis** changes the vibration plot between **Time** and **RPM**; the tacho plot remains against time. **Start [s]** and **End [s]** choose the visible time window. **View All** restores the full record. **View 4 period** selects a short window based on the lowest positive Order or Sine signal at the current start time; it does not calculate a period for Chirp or noise components.

Preview updates after you edit a setting. It uses the clean RPM profile: **Tacho Noise** affects only the tacho column in the exported file, not the preview or the vibration synthesis.

## Add noise to the exported tacho

Select **Tacho Noise** to enable its controls. **Jitter [rpm]** sets the standard deviation of added Gaussian speed variation (0–5,000 RPM). **Region** selects `all`, `start`, or `end`; **Region frac** (0.01–1.00, default 1.00) sets the fraction of the record affected by jitter at the selected end. With `all`, jitter affects the whole record. **Dropout rate** (0–1, default 0) is the per-sample chance of a dropout across the whole record, regardless of Region. At a dropout, the reported speed is multiplied by **Dropout gain** (0–1, default 0.5). The resulting tacho values are clipped at zero. These changes degrade only the exported `Tacho_Master` channel; the vibration channels still use the clean speed profile.

## Load a preset

Choose **Load Preset…**, select a **Dataset**, then choose one of its listed measurements and confirm. The preset replaces the current generation settings, including channels and components. It also sets the preview window to the full record; the preview's selected X axis remains as it was. You can edit the loaded values before exporting. This picker loads one measurement's signal settings; it does not write the whole dataset.

## Export the ASC file

1. Set up the record and choose **Export Signal**.
2. In the save dialog, choose a location and filename for the Siemens ASCII file. Canceling the dialog returns without generating a file.
3. The application generates and writes the record in a background job. On success, it reports the sample count and seed and adds the new ASC file to the [Data Pool](topic:data_management/intro).

The only **Export Format** choice is **ASC (Siemens Testlab)**. The file contains a time column, `Tacho_Master` in RPM, and one vibration column per channel, with each channel's name and unit. If the filename has no `.asc` suffix, the exporter adds it. Channel names containing a comma, square bracket, or apostrophe cannot be represented in the ASC header and cause the export to fail; the failure appears in the application log.

An order or fixed sine signal whose highest frequency (including a positive modulation sideband) exceeds half the sampling rate produces a Nyquist warning in the success message. The file is still written; the warning means the component will alias in sampled data.

For the full dataset library, see [Test datasets](topic:generation/datasets). To analyse an exported record, follow [Quick start](topic:quick_start/workflow) and open it as a [raw signal](topic:raw_data/intro) first.
