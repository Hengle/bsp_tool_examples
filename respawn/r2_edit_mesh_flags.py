from bsp_tool.branches.respawn import titanfall as r1
from bsp_tool.branches.respawn import titanfall2 as r2
from bsp_tool.branches.valve import source
from bsp_tool.utils import binary


lumps = {
    "TEXTURE_DATA": 0x02,
    "TEXTURE_DATA_STRING_DATA": 0x2B,
    "MESHES": 0x50}


def lump_header(bsp_file, lump_name: str) -> (int, int):
    bsp_file.seek(0x10 + (lumps[lump_name] * 0x10))
    return binary.read_struct(bsp_file, "2I")  # offset, length


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} OLD_BSP NEW_BSP")
        sys.exit()
    old_bsp_filename, new_bsp_filename = sys.argv[1:]

    # parse
    raw_bsp = list()  # unedited segments
    with open(old_bsp_filename, "rb") as bsp_file:
        assert binary.read_struct(bsp_file, "4sI") == (b"rBSP", 47), "not a Titanfall 2 .bsp!"
        # segments we will parse / edit
        headers = {
            lump_name: lump_header(bsp_file, lump_name)
            for lump_name in lumps}
        # ^ {"lump_name": (offset, length)}
        lump_order = sorted(headers, key=lambda k: headers[k])
        # ^ lump_name sorted by (offset, length)

        # NOTE: LumpClasses are collected by checking r2.LUMP_CLASSES["lump_name"] (or SPECIAL_LUMP_CLASSES for TDSD)
        offset, length = headers["TEXTURE_DATA"]
        sizeof = len(r1.TextureData().as_bytes())
        texture_data = [
            r1.TextureData.from_stream(bsp_file)
            for i in range(length // sizeof)]

        # NOTE: unedited, but useful for parsing
        offset, length = headers["TEXTURE_DATA_STRING_DATA"]
        texture_data_string_data = source.TextureDataStringData.from_bytes(bsp_file.read(length))

        offset, length = headers["MESHES"]
        sizeof = len(r2.Mesh().as_bytes())
        meshes = [
            r2.Mesh.from_stream(bsp_file)
            for i in range(length // sizeof)]

        # unedited segments
        bsp_file.seek(0)
        for lump_name in lump_order:
            offset, length = headers[lump_name]
            raw_bsp.append(bsp_file.read(bsp_file.tell() - offset))  # read until the start of this lump
            assert bsp_file.tell() == offset, "reached EOF prematurely"
            bsp_file.seek(offset + length)  # skip this lump's bytes
        raw_bsp.append(bsp_file.read())  # until EOF
        assert len(raw_bsp) == len(headers) + 1

    # edits
    for i, td in enumerate(texture_data):
        if 0x0080 & td.flags:
            texture_data[i].flags ^= 0x0080  # r1 water
            texture_data[i].flags |= 0x0800  # r2 water

    for i, mesh in enumerate(meshes):
        if 0x0080 & mesh.flags:
            meshes[i].flags ^= 0x0080  # r1 water
            meshes[i].flags |= 0x0800  # r2 water

    edited_bsp = {
        "TEXTURE_DATA": b"".join([td.as_bytes() for td in texture_data]),
        "TEXTURE_DATA_STRING_DATA": texture_data_string_data.as_bytes(),
        "MESHES": b"".join([mesh.as_bytes() for mesh in meshes])}
    # ^ {"lump_name": b"lump\x10as\x10bytes"}

    # write
    with open(new_bsp_filename, "wb") as bsp_file:
        for i, lump_name in enumerate(lump_order):
            bsp_file.write(raw_bsp[i])
            bsp_file.write(edited_bsp[lump_name])
        bsp_file.write(raw_bsp[-1])
