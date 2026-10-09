# Band RMS

Band RMS reads the RMS amplitude of the signal within a frequency range of a **[Spectrum 1D](topic:spectrum/intro)** graph. The shaded band gives you two edges to position; the value updates as you move them.

## Show the band

On the *Spectrum 1D* ribbon tab ([Spectrum 1D](topic:spectrum/intro)), check **Band RMS Cursors**. The checkbox starts off. It shows the band on the graph tab currently in front when that tab contains a spectrum. If another kind of tab is active, the app logs a warning and does not draw the band there.

When a spectrum is first drawn, the default band covers 10% to 35% of that spectrum's frequency span. Drag either edge to change the range. Drag the shaded band between the edges to move the whole range without changing its width. The edges stay within the spectrum's displayed span.

![Band RMS band on a spectrum](band_rms.en.png)

## What the value measures

The value uses the graph's **base curve**: the spectrum that opened the graph. Other curves added for comparison do not contribute to the same readout. Band RMS is always an RMS value in the channel's [physical unit](topic:units/intro), such as g or Pa; it is not the spectrum's displayed Peak value.

The calculation integrates the spectrum's energy per bin. If an edge crosses a bin, that bin contributes in proportion to the fraction of its frequency width inside the band. Moving an edge within a bin therefore changes the value smoothly instead of switching the whole bin in or out. The square root of the summed energy is the Band RMS.

In symbols, $L_\mathrm{RMS}=\sqrt{\sum_k w_k E_k}$, where $E_k$ is energy per bin in squared channel units and $w_k$ is the fraction of bin $k$ inside the band, from 0 to 1. For example, if one bin contains 4 g² and all other bins are zero, including that whole bin gives 2 g RMS; including half gives $\sqrt{2}\approx1.414$ g RMS.

The spectrum's **Linear**, **Power**, or **PSD** format, **RMS / Peak** amplitude choice, and linear or **dB** axis control how the spectrum is displayed. They do not change the Band RMS calculation for the same spectrum. The readout remains in the channel's physical unit and is labelled RMS. See [Amplitude & Format](topic:shared/amplitude_format) for the spectrum display choices.

In *Settings* → *View*, **X axis unit** changes the horizontal display scale and labels. A spectrum is calculated in frequency; even when its axis is shown in RPM, the band is kept in Hz and converted back before integration. Changing this display setting does not change the measured range or its value.

## Which curves support it

The readout needs a 1D spectrum behind the base curve. A time-domain channel that you compute in **Spectrum 1D** has one. A precomputed imported result that is already an order curve, such as a MASTA result ([Supported formats](topic:import/formats)), is an [order cut](topic:order_tracking/orders) rather than a spectrum and has no Band RMS band. If a displayed spectrum lacks energy per bin, the readout says **Band RMS unavailable**.

## What is saved

The **Band RMS Cursors** checkbox is stored in application settings, separately from the project, and is used as the preference for newly drawn spectra. Toggling it shows or hides the band on the graph tab currently in front; it does not switch the band on every graph already open.

The dragged range belongs to that graph while it is open. Saving and reopening a project restores the graph's spectrum, but the [project](topic:general/projects) does not save the custom Band RMS range. The reopened graph starts with the default range when the application preference is on.

Band RMS is one number from one spectrum. [Overall Level](topic:overall_level/intro) follows band energy through a record as a curve. For the tool that reads individual graph points, see [Cursor and Highlight](topic:tools/cursor).
