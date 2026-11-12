# Test fixtures

| File | What it is |
| --- | --- |
| `application_small.evtx` | A real 17-event Windows Application log. Used to check that binary `.evtx` files are read correctly on every OS. |
| `sample_events.xml` | A hand-written Event Viewer XML export (an `<Events>` root, with `RenderingInfo` message text) that covers the event shapes EventLens has to handle. |
| `sleepstudy_legacy.xml` | A reduced SleepStudy 1.1 report with six legacy `ConnectedStandby` sessions, retained for future compatibility tests. |

`application_small.evtx` is `samples/Application_no_crc32.evtx` from
[omerbenamram/evtx](https://github.com/omerbenamram/evtx), used under the MIT License:

> Copyright (c) 2019 Omer Ben-Amram
>
> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all
> copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
> SOFTWARE.

## Legacy SleepStudy fixture

`sleepstudy_legacy.xml` comes from the
[DigitalSocietySchool sample at commit `9689cd3`](https://github.com/DigitalSocietySchool/interactive_content/blob/9689cd362b1ec1855dce7d7c7ae086500d87182e/ParsingXML/sleepstudy-report.xml).
The source repository uses [CC0 1.0 Universal](https://github.com/DigitalSocietySchool/interactive_content/blob/master/LICENSE).

The reduced fixture replaces the computer name with `TEST-TABLET` and removes
the report GUID, scan metadata, hardware and OS metadata, battery identifiers
and serial numbers, `EnergyDrains`, and detailed child trees other than
`TopBlockers`. It preserves the six `ScenarioInstance` attribute sets, original
timestamps, and `TopBlockers` measurements and component names.

The current parser expects `Duration`, while these sessions use `CsDuration`.
