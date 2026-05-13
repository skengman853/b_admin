from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.vatbook_parser import list_sheet_names, parse_vatbook_workbook


class VatbookParserTests(unittest.TestCase):
    def test_parses_transaction_rows_and_following_annotations(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = Path(tmpdir) / "sample.xlsx"
            self._write_sample_workbook(workbook_path)

            self.assertEqual(list_sheet_names(workbook_path), ["VAT BOOK MAR - APR"])

            parsed = parse_vatbook_workbook(workbook_path)

        self.assertEqual(parsed.sheet_name, "VAT BOOK MAR - APR")
        self.assertEqual(len(parsed.transactions), 2)

        first = parsed.transactions[0]
        self.assertEqual(first.row_number, 16)
        self.assertEqual(first.pub, "Canal")
        self.assertEqual(str(first.transaction_date), "2026-03-05")
        self.assertEqual(str(first.debit_amount), "2857.46")
        self.assertEqual(first.category, "Resale - Diageo - Canal")
        self.assertEqual([annotation.annotation_type for annotation in first.annotations], ["invoice", "statement"])
        self.assertIn("9263279835", first.annotations[0].note)
        self.assertIn("Linked", first.annotations[1].note)

        second = parsed.transactions[1]
        self.assertEqual(second.row_number, 20)
        self.assertEqual(str(second.transaction_date), "2026-03-06")
        self.assertEqual(str(second.debit_amount), "1540.54")
        self.assertEqual([annotation.annotation_type for annotation in second.annotations], ["invoice", "invoice"])
        self.assertIn("873604", second.annotations[0].note)
        self.assertIn("873613", second.annotations[1].note)

    @staticmethod
    def _write_sample_workbook(path: Path) -> None:
        shared_strings = [
            "VAT BOOK MAR - APR",
            "Posted Account",
            "Pub",
            "Date",
            "Desc1",
            "Desc2",
            "Debit",
            "Credit",
            "Type",
            "Category",
            "Resale @ 23%",
            "BankAcc",
            "Canal",
            "D/D DIAGEO IRELAND",
            "IE26030516200375",
            "Direct Debit",
            "Resale - Diageo - Canal",
            "Invoice",
            "Diageo TCT-INV - 219 - Invoice Number - 9263279835 - Date - 17.02.2026 - Linked",
            "Statement",
            "Diageo Stmt - TCT060 - Statement - Date - 31.03.2026 - Linked",
            "*INET LovellsBros",
            "Renovation",
            "Lovell Bros Inv TCT461 - INVOICE No - 873604 - Date - 03-02-2026 - Linked",
            "Lovell Bros Inv TCT462 - INVOICE No - 873613 - Date - 03-02-2026 - Linked",
        ]

        workbook_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="VAT BOOK MAR - APR" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>
"""
        workbook_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>
"""
        shared_strings_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="{count}" uniqueCount="{count}">
{items}
</sst>
""".format(
            count=len(shared_strings),
            items="\n".join(f"  <si><t>{value}</t></si>" for value in shared_strings),
        )
        sheet_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1">
      <c r="B1" t="s"><v>1</v></c>
      <c r="C1" t="s"><v>2</v></c>
      <c r="D1" t="s"><v>3</v></c>
      <c r="E1" t="s"><v>4</v></c>
      <c r="F1" t="s"><v>5</v></c>
      <c r="G1" t="s"><v>6</v></c>
      <c r="H1" t="s"><v>7</v></c>
      <c r="I1" t="s"><v>8</v></c>
      <c r="J1" t="s"><v>9</v></c>
      <c r="K1" t="s"><v>10</v></c>
    </row>
    <row r="16">
      <c r="B16" t="s"><v>11</v></c>
      <c r="C16" t="s"><v>12</v></c>
      <c r="D16"><v>46086</v></c>
      <c r="E16" t="s"><v>13</v></c>
      <c r="F16" t="s"><v>14</v></c>
      <c r="G16"><v>2857.46</v></c>
      <c r="I16" t="s"><v>15</v></c>
      <c r="J16" t="s"><v>16</v></c>
      <c r="K16"><v>2857.46</v></c>
    </row>
    <row r="17">
      <c r="D17" t="s"><v>17</v></c>
      <c r="F17" t="s"><v>18</v></c>
    </row>
    <row r="18">
      <c r="D18" t="s"><v>19</v></c>
      <c r="F18" t="s"><v>20</v></c>
    </row>
    <row r="20">
      <c r="B20" t="s"><v>11</v></c>
      <c r="C20" t="s"><v>12</v></c>
      <c r="D20"><v>46087</v></c>
      <c r="E20" t="s"><v>21</v></c>
      <c r="G20"><v>1540.54</v></c>
      <c r="I20" t="s"><v>15</v></c>
      <c r="J20" t="s"><v>22</v></c>
      <c r="L20"><v>1540.54</v></c>
    </row>
    <row r="21">
      <c r="D21" t="s"><v>17</v></c>
      <c r="F21" t="s"><v>23</v></c>
    </row>
    <row r="22">
      <c r="F22" t="s"><v>24</v></c>
    </row>
  </sheetData>
</worksheet>
"""

        with ZipFile(path, "w") as archive:
            archive.writestr("xl/workbook.xml", workbook_xml)
            archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
            archive.writestr("xl/sharedStrings.xml", shared_strings_xml)
            archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)


if __name__ == "__main__":
    unittest.main()
