# cp1215

`cp1215` is a small Linux command-line utility for the HP Color LaserJet
CP1215 / CP1210 series.

It talks directly to the USB printer device and exposes maintenance and status
features that are not normally available through the Linux print path.

## Features

- Show printer status with decoded status codes
- Show toner and supply information
- Show printer configuration, usage, firmware, page count, and memory details
- Show the printer event log with decoded error meanings
- Run the printer cleaning cycle
- Run color calibration
- Check device access with `doctor`

The utility is a single Python script and uses only the Python standard
library. It does not require CUPS, `pycups`, `click`, or any other Python
package.

## Install

Clone the repository, then run the script from the checkout:

```sh
./cp1215 status
```

You can also put `cp1215` somewhere on your `PATH`.

## Usage

Read-only commands:

```sh
cp1215 doctor
cp1215 status
cp1215 supplies
cp1215 config
cp1215 events
cp1215 info
```

Service commands that make the printer do something:

```sh
cp1215 service clean
cp1215 service calibrate
```

JSON output is available for query commands:

```sh
cp1215 status --json
cp1215 supplies --json
cp1215 events --json
```

The default USB device is `/dev/usb/lp0`. To use a different device:

```sh
cp1215 --device /dev/usb/lp1 status
```

Global options, including `--device`, must appear before the subcommand.

## Testing

Run the standard-library test suite from the repository root:

```sh
python -m unittest -v
```

## Permissions

The utility needs read/write access to the USB printer device. If `doctor`
reports a permission problem, either run the command with suitable privileges
or adjust your local group/udev permissions so your user can access
`/dev/usb/lp0`.

## Notes

Cleaning and calibration use printer firmware service actions over
HTTP-over-USB. They are separate from normal document printing and do not use
CUPS.

This project is not affiliated with or endorsed by HP. HP, LaserJet, and
related names are trademarks of their owners. No HP firmware, drivers, manuals,
or other proprietary files are distributed in this repository.
