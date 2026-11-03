"""Package the validated VGA hardware platform; no Linux build or Vivado rerun."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
BUILD = ROOT / "build"
OUT = ROOT / "deliverables" / "hardware_handoff"
ARCHIVE = OUT.with_suffix(".zip")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    subprocess.run([sys.executable, str(ROOT / "scripts/verify_board_reference.py"), "--vga"],
                   cwd=WORKSPACE, check=True)
    validation = json.loads((BUILD / "vga_42mhz_validation.json").read_text(encoding="utf-8"))
    for name in ("vga_system.hdf", "vga_system.bit"):
        data = (BUILD / name).read_bytes()
        expected = validation["artifacts"][name]
        require(len(data) == expected["bytes"] and digest(data) == expected["sha256"],
                f"Validated artifact changed: {name}; revalidate before packaging")
    with zipfile.ZipFile(BUILD / "vga_system.hdf") as hdf:
        require(hdf.testzip() is None, "HDF ZIP corruption")
        required = {"system.hwh", "system_bd.tcl", "ps7_init.c", "ps7_init.tcl", "vga_system.bit"}
        require(required.issubset(hdf.namelist()), "Missing HDF members")
        require(hdf.read("vga_system.bit") == (BUILD / "vga_system.bit").read_bytes(),
                "Embedded and standalone bitstreams differ")
        hwh = ET.fromstring(hdf.read("system.hwh"))
        hdf_members = hdf.namelist()
    require(hwh.get("VIVADOVERSION") == "2019.1", "Unexpected Vivado version")
    ps = next(m for m in hwh.iter("MODULE") if m.get("INSTANCE") == "ps7")
    params = {p.get("NAME"): p.get("VALUE") for p in ps.iter("PARAMETER")}
    expected_ps = {
        "PCW_PACKAGE_NAME": "clg484",
        "PCW_UIPARAM_DDR_FREQ_MHZ": "533.333333",
        "PCW_DDR_RAM_HIGHADDR": "0x1FFFFFFF",
        "PCW_CRYSTAL_PERIPHERAL_FREQMHZ": "33.333333",
        "PCW_FPGA0_PERIPHERAL_FREQMHZ": "50",
        "PCW_USE_S_AXI_HP0": "1",
        "PCW_S_AXI_HP0_DATA_WIDTH": "64",
        "PCW_UART0_PERIPHERAL_ENABLE": "1",
        "PCW_UART0_UART0_IO": "EMIO",
        "PCW_UART0_BAUD_RATE": "115200",
        "PCW_UART1_PERIPHERAL_ENABLE": "0",
        "PCW_SD0_PERIPHERAL_ENABLE": "1",
        "PCW_SD0_SD0_IO": "MIO 40 .. 45",
        "PCW_SD0_GRP_CD_ENABLE": "1",
        "PCW_SD0_GRP_CD_IO": "MIO 47",
        "PCW_QSPI_PERIPHERAL_ENABLE": "0",
        "PCW_ENET0_PERIPHERAL_ENABLE": "0",
        "PCW_USB0_PERIPHERAL_ENABLE": "0",
    }
    for name, value in expected_ps.items():
        require(params.get(name) == value, f"HDF PS mismatch: {name}={params.get(name)}")
    ranges = {m.get("INSTANCE"): dict(m.attrib) for m in hwh.iter("MEMRANGE")
              if m.get("INSTANCE") in {"capture", "dma"}}
    for name, base, high in (("capture", "0x40000000", "0x4003FFFF"),
                             ("dma", "0x40400000", "0x4040FFFF")):
        require(ranges.get(name, {}).get("BASEVALUE") == base and
                ranges.get(name, {}).get("HIGHVALUE") == high, f"HDF address mismatch: {name}")

    files = {
        "system.hdf": BUILD / "vga_system.hdf",
        "system.bit": BUILD / "vga_system.bit",
        "README.md": ROOT / "docs/HARDWARE_HANDOFF.md",
        "docs/REGISTER_MAP.md": ROOT / "docs/REGISTER_MAP.md",
        "reference/camera_diag.c": ROOT / "sdk/camera_diag.c",
        "reference/ov5640_vga_regs.h": ROOT / "sdk/ov5640_vga_regs.h",
    }
    for name in ("camera_pins.xdc", "known_board.xdc", "timing_verified.xdc", "camera_wiring.json",
                 "board_reference.tcl", "board_reference_provenance.json", "ov5640_vga_rgb565.json"):
        files["config/" + name] = ROOT / "config" / name
    for name in ("vga_implemented_timing.rpt", "vga_implemented_cdc.rpt", "vga_implemented_bus_skew.rpt",
                 "vga_implemented_drc.rpt", "vga_camera_io_timing.rpt", "vga_42mhz_validation.json",
                 "vga_board_reference_validation.json"):
        files["reports/" + name] = BUILD / name
    for name in ("vga_42mhz_final_implementation.log", "vga_42mhz_stream_sim.log",
                 "vga_42mhz_dma_sim.log", "vga_sdk_build.log"):
        files["logs/" + name] = WORKSPACE / "logs" / name
    for name, source in files.items():
        require(source.is_file(), f"Missing delivery input: {source}")
    allowed = set(files) | {"manifest.json", "SHA256SUMS"}
    if OUT.exists():
        unknown = {p.relative_to(OUT).as_posix() for p in OUT.rglob("*") if p.is_file()} - allowed
        require(not unknown, f"Unexpected files in managed output; preserve and review: {sorted(unknown)}")
    for name, source in files.items():
        target = OUT / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    manifest = {
        "format": "smart-zynq-sl-hardware-handoff-v1",
        "scope": "PS/PL hardware export only; Linux and OpenCV owned by software team",
        "board": "Smart ZYNQ SL V1.1", "part": "xc7z020clg484-1",
        "vivado_version": hwh.get("VIVADOVERSION"), "hdf_timestamp": hwh.get("TIMESTAMP"),
        "physical_validation": False, "linux_boot_verified": False,
        "opencv_included": False, "embedded_bit_matches_standalone": True,
        "hdf_members": hdf_members, "ps_parameters_verified": expected_ps,
        "memory_ranges": ranges,
        "capture": {"width": 640, "height": 480, "format": "RGB565", "frame_bytes": 614400,
                    "backend": "AXI DMA S2MM to HP0 DDR", "mode": "requested full-frame snapshot"},
        "validation_record": "reports/vga_42mhz_validation.json",
        "files": {name: {"bytes": (OUT/name).stat().st_size,
                         "sha256": digest((OUT/name).read_bytes())} for name in sorted(files)},
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    payload_names = sorted(set(files) | {"manifest.json"})
    checksums = {name: digest((OUT / name).read_bytes()) for name in payload_names}
    (OUT / "SHA256SUMS").write_text("".join(f"{value}  {name}\n" for name, value in checksums.items()), encoding="utf-8")
    with zipfile.ZipFile(ARCHIVE, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name in sorted(allowed):
            bundle.write(OUT / name, "hardware_handoff/" + name)
    with zipfile.ZipFile(ARCHIVE) as bundle:
        require(bundle.testzip() is None, "Delivery ZIP corruption")
        require(set(bundle.namelist()) == {"hardware_handoff/" + n for n in allowed}, "Archive file list mismatch")
        for name, value in checksums.items():
            require(digest(bundle.read("hardware_handoff/" + name)) == value, f"Archive hash mismatch: {name}")
        require(bundle.read("hardware_handoff/SHA256SUMS") == (OUT / "SHA256SUMS").read_bytes(),
                "Archive checksum table mismatch")
    archive_hash = digest(ARCHIVE.read_bytes())
    ARCHIVE.with_suffix(".zip.sha256").write_text(f"{archive_hash}  {ARCHIVE.name}\n", encoding="utf-8")
    print(json.dumps({"archive": str(ARCHIVE), "archive_bytes": ARCHIVE.stat().st_size,
                      "archive_sha256": archive_hash, "files_verified": len(allowed),
                      "hdf_verified": True, "physical_validation": False}, indent=2))


if __name__ == "__main__":
    main()
