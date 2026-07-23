import contextlib
import importlib.util
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_loader(
    "cp1215_cli",
    SourceFileLoader("cp1215_cli", str(ROOT / "cp1215")),
)
cp1215 = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = cp1215
SPEC.loader.exec_module(cp1215)


SUPPLIES_SAMPLE = """@PJL INFO SUPPLIES
CARTRIDGE = BLACK
Type = NONHP
ReorderPN = CB540A
PercentRemaining = 75
PagesRemaining = 1914
SerialNumber = 3651141890
PageCount = 286

CARTRIDGE = CYAN
Type = Unknown
ReorderPN = CB541A
PercentRemaining = 99
PagesRemaining = 1397
\f"""


CONFIG_SAMPLE = """@PJL INFO CONFIG
PAPERS [3 ENUMERATED]
\tLETTER
\tLEGAL
\tA4
LANGUAGES [5 ENUMERATED]
\tZJS
\tHBS
\tPJL
\tACL
\tHTTP
MEMORY = 14477328
\f"""


LOG_SAMPLE = """@PJL INFO LOG
ErrCode0 = 21.0000
PageCount0 = 710
ErrCode1 = 13.0200
PageCount1 = 702
MARSLOGEND = 1
\f"""


PAGECOUNT_SAMPLE = """@PJL INFO PAGECOUNT
727
\f"""


PRODINFO_SAMPLE = """@PJL INFO PRODINFO
ProductName = HP Color LaserJet CP1215
ProductSerialNumber = CNAC82C08J
FirmwareDateCode = 20071207
ServiceID = 18163
\f"""


TRACKING_SAMPLE = """@PJL INFO TRACKING
TotalPagesPrinted = 727
TotalDuplexPagesPrinted = 6
TotalPagesMispicked = 6
TotalPagesJammed = 10
\f"""


MEMORY_SAMPLE = """@PJL INFO MEMORY
TOTAL=14477328
\f"""


CSV_SAMPLE = """@PJL INFO DENSITYLUT
KLUT=85,6,27,59
CLUT=85,1,11,39
\f"""


SCALAR_SAMPLE = """@PJL INQUIRE REGIONID
52
\f"""


class Cp1215Tests(unittest.TestCase):
    def test_parse_status(self):
        data = cp1215.parse_key_values('@PJL INFO STATUS\nCODE=10403\nDISPLAY=""\nONLINE=TRUE\n\f')
        self.assertEqual(data["code"], 10403)
        self.assertEqual(data["display"], "")
        self.assertIs(data["online"], True)

    def test_parse_supplies(self):
        data = cp1215.parse_supplies(SUPPLIES_SAMPLE)
        self.assertEqual(len(data["cartridges"]), 2)
        self.assertEqual(data["cartridges"][0]["color"], "BLACK")
        self.assertEqual(data["cartridges"][0]["percent_remaining"], 75)
        self.assertEqual(data["cartridges"][0]["reorder_pn"], "CB540A")
        self.assertEqual(data["cartridges"][1]["pages_remaining"], 1397)

    def test_parse_config(self):
        data = cp1215.parse_config(CONFIG_SAMPLE)
        self.assertEqual(data["values"]["memory"], 14477328)
        self.assertEqual(data["sections"]["papers"], ["LETTER", "LEGAL", "A4"])
        self.assertEqual(data["sections"]["languages"][-1], "HTTP")

    def test_json_serializable(self):
        json.dumps(cp1215.parse_supplies(SUPPLIES_SAMPLE), sort_keys=True)

    def test_status_code_label(self):
        self.assertEqual(cp1215.status_code_label(10403), "Unsupported or non-HP cartridge (10403)")
        self.assertEqual(cp1215.status_code_label(10600), "Calibration DMAX (10600)")
        self.assertEqual(cp1215.status_code_label(10209), "Black toner low (10209)")
        self.assertEqual(cp1215.status_code_label(41004), "Load tray 1 with A4 (41004)")
        self.assertEqual(cp1215.status_code_label(42003), "Paper jam in output area (42003)")
        self.assertEqual(cp1215.status_code_label(50004), "Cyan scanner laser failure (50004)")
        self.assertEqual(cp1215.status_code_label(50006), "Fuser warm-up failure (50006)")
        self.assertEqual(cp1215.status_code_label(50020), "Fan error (50020)")
        self.assertEqual(cp1215.status_code_label(50022), "Paper path error (50022)")
        self.assertEqual(cp1215.status_code_label(99999), "99999")

    def test_status_code_table_uses_five_digit_codes(self):
        self.assertTrue(
            all(code == 0 or 10000 <= code <= 99999 for code in cp1215.STATUS_CODE_NAMES)
        )

    def test_service_parser(self):
        parser = cp1215.build_parser()
        args = parser.parse_args(["service", "clean"])
        self.assertEqual(args.service_command, "clean")
        self.assertIs(args.func, cp1215.command_clean)

        args = parser.parse_args(["service", "calibrate"])
        self.assertEqual(args.service_command, "calibrate")
        self.assertIs(args.func, cp1215.command_calibrate)

    def test_action_commands_are_not_top_level(self):
        parser = cp1215.build_parser()
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                parser.parse_args(["clean"])
            with self.assertRaises(SystemExit):
                parser.parse_args(["calibrate"])

    def test_parse_event_log(self):
        data = cp1215.parse_event_log(LOG_SAMPLE)
        self.assertEqual(len(data["events"]), 2)
        self.assertEqual(data["events"][0]["event"], 0)
        self.assertEqual(data["events"][0]["err_code"], "21.0000")
        self.assertEqual(data["events"][0]["err_name"], "Paper punt error")
        self.assertEqual(data["events"][0]["err_label"], "Paper punt error (21.0000)")
        self.assertEqual(data["events"][0]["page_count"], 710)
        self.assertEqual(data["events"][1]["err_code"], "13.0200")
        self.assertEqual(data["events"][1]["err_name"], "Paper jam error")

    def test_event_log_code_label(self):
        self.assertEqual(
            cp1215.event_log_code_label("41.2000"),
            "Beam detect malfunction (41.2000)",
        )
        self.assertEqual(cp1215.event_log_code_label("41.3000"), "Unexpected size (41.3000)")
        self.assertEqual(cp1215.event_log_code_label("49.0000"), "49 error (49.0000)")
        self.assertEqual(cp1215.event_log_code_label("50.1000"), "50.1 fuser error (50.1000)")
        self.assertEqual(cp1215.event_log_code_label("50.0000"), "All fuser errors (50.0000)")
        self.assertEqual(cp1215.event_log_code_label("51.2000"), "51.20 error (51.2000)")
        self.assertEqual(cp1215.event_log_code_label("51.0000"), "Laser error (51.0000)")
        self.assertEqual(cp1215.event_log_code_label("52.0000"), "All scanner errors (52.0000)")
        self.assertEqual(cp1215.event_log_code_label("54.1c00"), "54.1C error (54.1c00)")
        self.assertEqual(cp1215.event_log_code_label("55.1000"), "55.1 error (55.1000)")
        self.assertEqual(cp1215.event_log_code_label("57.0000"), "Fan error (57.0000)")
        self.assertEqual(cp1215.event_log_code_label("59.A000"), "59.A0 error (59.A000)")
        self.assertEqual(cp1215.event_log_code_label("79.0000"), "79 service (79.0000)")
        self.assertEqual(cp1215.event_log_code_label("99.0000"), "99.0000")

    def test_parse_pagecount(self):
        data = cp1215.parse_pagecount(PAGECOUNT_SAMPLE)
        self.assertEqual(data["page_count"], 727)

    def test_parse_product_info(self):
        data = cp1215.parse_key_values(PRODINFO_SAMPLE)
        self.assertEqual(data["product_name"], "HP Color LaserJet CP1215")
        self.assertEqual(data["product_serial_number"], "CNAC82C08J")
        self.assertEqual(data["service_id"], 18163)

    def test_parse_tracking(self):
        data = cp1215.parse_key_values(TRACKING_SAMPLE)
        self.assertEqual(data["total_pages_printed"], 727)
        self.assertEqual(data["total_pages_jammed"], 10)

    def test_parse_memory(self):
        data = cp1215.parse_memory(MEMORY_SAMPLE)
        self.assertEqual(data["total"], 14477328)
        self.assertEqual(data["total_bytes"], 14477328)

    def test_parse_csv_values(self):
        data = cp1215.parse_csv_values(CSV_SAMPLE)
        self.assertEqual(data["values"]["klut"], [85, 6, 27, 59])
        self.assertEqual(data["values"]["clut"], [85, 1, 11, 39])

    def test_parse_scalar_response(self):
        data = cp1215.parse_scalar_response(SCALAR_SAMPLE)
        self.assertEqual(data["value"], 52)

    def test_fetch_status_preserves_raw_response(self):
        client = mock.Mock(spec=cp1215.Cp1215Client)
        parsed = cp1215.parse_key_values(
            '@PJL INFO STATUS\nCODE=10403\nDISPLAY=""\nONLINE=TRUE\n\f'
        )
        client.query_parsed.return_value = parsed

        data = cp1215.fetch_status(client)

        self.assertEqual(data["raw"], parsed["raw"])
        self.assertEqual(data["code_name"], "Unsupported or non-HP cartridge")
        self.assertEqual(
            data["code_label"],
            "Unsupported or non-HP cartridge (10403)",
        )

    def test_fetch_info_pairs_commands_with_parsers(self):
        responses = {
            "@PJL INFO PAGECOUNT": PAGECOUNT_SAMPLE,
            "@PJL INFO PRODINFO": PRODINFO_SAMPLE,
            "@PJL INFO TRACKING": TRACKING_SAMPLE,
            "@PJL INFO MEMORY": MEMORY_SAMPLE,
            "@PJL INFO UTMEMORY": "@PJL INFO UTMEMORY\nTotalMemory=14\n\f",
            "@PJL INQUIRE SERVICEID": '@PJL INQUIRE SERVICEID\n"18163"\n\f',
            "@PJL INQUIRE REGIONID": SCALAR_SAMPLE,
        }
        client = mock.Mock(spec=cp1215.Cp1215Client)

        def query_parsed(command, parser):
            return parser(responses[command])

        client.query_parsed.side_effect = query_parsed
        data = cp1215.fetch_info(client)

        self.assertEqual(data["pagecount"]["page_count"], 727)
        self.assertEqual(data["product"]["product_name"], "HP Color LaserJet CP1215")
        self.assertEqual(data["service_id"]["value"], 18163)
        self.assertEqual(
            [call.args[0] for call in client.query_parsed.call_args_list],
            list(responses),
        )

    def test_text_renderers_use_structured_reports(self):
        config = {
            "capabilities": cp1215.parse_config(CONFIG_SAMPLE),
            "paper": cp1215.parse_key_values("@PJL INFO UTPAPER\nSource=Tray2\n\f"),
            "print": cp1215.parse_key_values("@PJL INFO UTPRINT\nCopies=1\n\f"),
            "product_settings": cp1215.parse_key_values(
                "@PJL INFO UTPRODSETTING\nSleep=TRUE\n\f"
            ),
            "density_lut": cp1215.parse_csv_values(CSV_SAMPLE),
            "color_metrics": cp1215.parse_csv_values(CSV_SAMPLE),
            "bow_tilt": cp1215.parse_csv_values(CSV_SAMPLE),
        }
        info = {
            "pagecount": cp1215.parse_pagecount(PAGECOUNT_SAMPLE),
            "product": cp1215.parse_key_values(PRODINFO_SAMPLE),
            "tracking": cp1215.parse_key_values(TRACKING_SAMPLE),
            "memory": cp1215.parse_memory(MEMORY_SAMPLE),
            "user_memory": cp1215.parse_key_values(
                "@PJL INFO UTMEMORY\nTotalMemory=14\nAvailableMemory=7\n\f"
            ),
            "service_id": cp1215.parse_scalar_response(
                '@PJL INQUIRE SERVICEID\n"18163"\n\f'
            ),
            "region_id": cp1215.parse_scalar_response(SCALAR_SAMPLE),
        }

        config_text = cp1215.render_config_text(config)
        info_text = cp1215.render_info_text(info)

        self.assertIn("Capabilities\n", config_text)
        self.assertIn("Paper Handling\n", config_text)
        self.assertIn("Density LUT\n", config_text)
        self.assertIn("Product\n", info_text)
        self.assertIn("page_count", info_text)
        self.assertIn("Usage\n", info_text)

    def test_send_pjl_command_wraps_uel(self):
        calls = []

        def fake_send(payload, device, timeout=2.0, limit=8192, require_response=False):
            calls.append((payload, device, timeout, limit, require_response))
            return ""

        original = cp1215._transact
        cp1215._transact = fake_send
        try:
            client = cp1215.Cp1215Client("/dev/test")
            client.send_pjl_command("@PJL INFO STATUS", timeout=1.0)
        finally:
            cp1215._transact = original

        self.assertEqual(
            calls,
            [
                (
                    cp1215.UEL + b"@PJL INFO STATUS\r\n" + cp1215.UEL,
                    "/dev/test",
                    1.0,
                    8192,
                    False,
                )
            ],
        )

    def test_write_all_retries_short_writes(self):
        writes = []

        def fake_write(fd, payload):
            writes.append((fd, bytes(payload)))
            return 1 if len(writes) == 1 else len(payload)

        with mock.patch.object(cp1215.os, "write", side_effect=fake_write):
            cp1215._write_all(7, b"abcd", timeout=1.0)

        self.assertEqual(writes, [(7, b"abcd"), (7, b"bcd")])

    def test_client_rejects_regular_file_without_modifying_it(self):
        original = b"do not overwrite"
        with tempfile.NamedTemporaryFile() as device:
            device.write(original)
            device.flush()

            with self.assertRaisesRegex(cp1215.DeviceAccessError, "non-character device"):
                client = cp1215.Cp1215Client(device.name)
                client.send_pjl_command("printer command", timeout=0)

            device.seek(0)
            self.assertEqual(device.read(), original)

    def test_client_wraps_write_errors(self):
        fake_stat = os.stat_result((stat.S_IFCHR, 0, 0, 0, 0, 0, 0, 0, 0, 0))
        with (
            mock.patch.object(cp1215.os, "open", return_value=7),
            mock.patch.object(cp1215.os, "fstat", return_value=fake_stat),
            mock.patch.object(cp1215.os, "write", side_effect=OSError(5, "device vanished")),
            mock.patch.object(cp1215.os, "close"),
        ):
            with self.assertRaisesRegex(cp1215.DeviceAccessError, "device vanished"):
                client = cp1215.Cp1215Client("/dev/test")
                client.send_pjl_command("printer command")

    def test_build_http_post(self):
        body = b"\tSID+CleaningMode=1& \r\n"
        payload = cp1215.build_http_post("/ssi/xml_config.html", body)
        self.assertEqual(
            payload,
            cp1215.UEL
            + b"@PJL ENTER LANGUAGE=HTTP\r\n"
            + b"POST /ssi/xml_config.html HTTP/1.1 \r\n"
            + b"CONTENT-LENGTH:23 \r\n\r\n"
            + body,
        )

    def test_client_post_setting(self):
        calls = []

        def fake_send(payload, device, timeout=2.0, limit=8192, require_response=False):
            calls.append((payload, device, timeout, limit, require_response))
            return ""

        original = cp1215._transact
        cp1215._transact = fake_send
        try:
            client = cp1215.Cp1215Client("/dev/test")
            client.post_setting("FunctionGo", 1, timeout=5.0)
        finally:
            cp1215._transact = original

        self.assertEqual(len(calls), 1)
        payload, device, timeout, limit, require_response = calls[0]
        self.assertEqual(device, "/dev/test")
        self.assertEqual(timeout, 5.0)
        self.assertEqual(limit, 8192)
        self.assertIs(require_response, False)
        self.assertIn(b"CONTENT-LENGTH:21 \r\n\r\n\tSID+FunctionGo=1& \r\n", payload)

    def test_command_calibrate_sequence(self):
        original_wait = cp1215.wait_for_calibration_complete
        cp1215.wait_for_calibration_complete = lambda client: [10001]
        try:
            args = type("Args", (), {})()
            client = mock.Mock(spec=cp1215.Cp1215Client)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(cp1215.command_calibrate(args, client), 0)
        finally:
            cp1215.wait_for_calibration_complete = original_wait

        self.assertIn("Final status: Ready (10001)", output.getvalue())
        self.assertEqual(
            client.post_setting.call_args_list,
            [
                mock.call("CalibrateAll", 1, timeout=5.0),
                mock.call("FunctionGo", 1, timeout=5.0),
            ],
        )

    def test_wait_for_action_complete_raises_if_busy_at_timeout(self):
        clock = [0.0]

        def fake_monotonic():
            clock[0] += 0.4
            return clock[0]

        client = mock.Mock(spec=cp1215.Cp1215Client)
        client.status_codes.return_value = [10031]
        with (
            mock.patch.object(cp1215.time, "monotonic", side_effect=fake_monotonic),
            mock.patch.object(cp1215.time, "sleep"),
        ):
            with self.assertRaisesRegex(
                cp1215.Cp1215Error,
                r"Timed out.*Engine cleaning \(10031\)",
            ):
                cp1215.wait_for_action_complete(client, {10031}, timeout=1.0)

    def test_wait_for_action_complete_propagates_device_errors(self):
        error = cp1215.DeviceAccessError("printer disconnected")
        client = mock.Mock(spec=cp1215.Cp1215Client)
        client.status_codes.side_effect = error
        with mock.patch.object(cp1215.time, "sleep") as sleep:
            with self.assertRaisesRegex(cp1215.DeviceAccessError, "printer disconnected"):
                cp1215.wait_for_action_complete(client, {10031}, timeout=1.0)

        sleep.assert_not_called()

    def test_doctor_rejects_malformed_status_response(self):
        args = type("Args", (), {"json": True})()
        client = mock.Mock(spec=cp1215.Cp1215Client)
        client.device = "/dev/test"
        client.query_parsed.return_value = {"raw": "", "code": True, "online": True}
        output = io.StringIO()

        with (
            mock.patch.object(cp1215.os.path, "exists", return_value=True),
            mock.patch.object(cp1215.os, "access", return_value=True),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(cp1215.command_doctor(args, client), 1)

        result = json.loads(output.getvalue())
        status_check = result["checks"][-1]
        self.assertIs(status_check["ok"], False)
        self.assertIn("Malformed PJL status response", status_check["detail"])


if __name__ == "__main__":
    unittest.main()
