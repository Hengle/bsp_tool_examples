import ctypes
import itertools
import os
import time

import bsp_tool
import numpy as np
from OpenGL.GL import *
from OpenGL.GL.shaders import compileShader, compileProgram
from OpenGL.GLU import *
from sdl2 import *  # .dll import is busted

from utilities import camera
from utilities import vector


camera.sensitivity = 2


def fan_range(start, length):
    out = []
    for i in range(start + 2, start + length):
        out.extend([start, i - 1, i])
    return out


# TODO: select shaders and triangulation mode from bsp version & mod
def main(width, height, bsp):
    SDL_Init(SDL_INIT_VIDEO)
    window = SDL_CreateWindow(bytes(bsp.filename, "utf-8"),
                              SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED,
                              width, height, SDL_WINDOW_OPENGL)
    glContext = SDL_GL_CreateContext(window)

    glClearColor(.5, .5, .5, 0)
    # glEnable(GL_CULL_FACE)
    glEnable(GL_DEPTH_TEST)
    glFrontFace(GL_CW)
    glPointSize(4)
    glPolygonMode(GL_BACK, GL_LINE)
    gluPerspective(120, width / height, 0.1, 1000000)

    conversion_start = time.time()

    # Team Fortress 2 FACES
    if bsp.bsp_version == 20:
        # TODO: indentify materials & location in buffer
        # -- this can allow for transparent trigger brushes
        # -- alternatively, identify faces from the model lump
        vertices = []
        indices = []
        for face_index, face in enumerate(bsp.FACES):
            tex_info = bsp.TEXINFO[face.tex_info]
            tex_data = bsp.TEXDATA[tex_info.tex_data]
            texture_name = bsp.TEXDATA_STRING_DATA[tex_data.tex_data_string_index]
            if "TRIGGER" in texture_name:
                continue
            # huh = face.first_edge
            # heh = bsp.SURFEDGES[huh:(huh + face.num_edges)]
            # ugh = [bsp.EDGES[ass][0] if ass >= 0 else bsp.EDGES[-ass][1] for ass in heh][::2]
            # oof = {ugh.count(wha) for wha in ugh}
            # if oof != {1}:
            #     continue
            if face.disp_info == -1:
                face_vertices = bsp.vertices_of_face(face_index)
                indices.extend(fan_range(len(vertices), len(face_vertices)))
                vertices.extend(face_vertices)
            else:
                face_vertices = bsp.vertices_of_displacement(face_index)
                power = bsp.DISP_INFO[face.disp_info].power
                disp_indices = bsp.mod.displacement_indices(power)
                indices.extend([len(vertices) + i for i in disp_indices])
                vertices.extend(face_vertices)
        vertices = list(itertools.chain(*[itertools.chain(*v) for v in vertices]))

    # Titanfall 2 & Apex Legends MESHES
    elif bsp.bsp_version >= 37:
        vertices = []
        indices = []
        for mesh_index, mesh in enumerate(bsp.MESHES):
            for vertex in bsp.vertices_of_mesh(mesh_index):
                position = bsp.VERTICES[vertex.position_index]
                normal = bsp.VERTEX_NORMALS[vertex.normal_index]
                uv = vertex.uv
                vertices.extend((*position, *normal, *uv))
                indices.append(len(indices))
    else:
        raise NotImplementedError("BSP v{bsp.bsp_version} is not supported")
    conversion_end = time.time()
    print(bsp.filename.upper(), end=" ")
    print(f"{bsp.bytesize // 1024:,}KB BSP", end=" >>> ")
    print(f"{len(vertices) // 9:,} TRIS", end=" & ")
    print(f"{(len(vertices) * 4) // 1024:,}KB VRAM")
    print(f"Converted to geometry in {(conversion_end - conversion_start) * 1000:,.3f}ms")

    VERTEX_BUFFER, INDEX_BUFFER = glGenBuffers(2)
    glBindBuffer(GL_ARRAY_BUFFER, VERTEX_BUFFER)
    glBufferData(GL_ARRAY_BUFFER, len(vertices) * 4, np.array(vertices, dtype=np.float32), GL_STATIC_DRAW)
    glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, INDEX_BUFFER)
    glBufferData(GL_ELEMENT_ARRAY_BUFFER, len(indices) * 4, np.array(indices, dtype=np.uint32), GL_STATIC_DRAW)

    # SHADERS
    shader_folder = "shaders/"
    render_mode = "flat"
    major, minor = glGetIntegerv(GL_MAJOR_VERSION), glGetIntegerv(GL_MINOR_VERSION)
    print(f"OpenGL Version {major}.{minor}")
    if major >= 4:  # Assuming GLSL 450
        shader_folder += "450_CORE"
    elif major == 3:  # if GLSL 450 not supported, use GLES 300
        shader_folder += "300_ES"
    else:
        raise NotImplementedError("GLSL Version ({major, minor}) is unsupported (too low)!")

    # SHADER COMPILATION
    def compile_shader(filename, shader_type):
        return compileShader(open(filename, "rb"), shader_type)
    # Team Fortress 2 & Vindictus FACES
    # brush_shader
    vert_shader = compile_shader(f"{shader_folder}/brush.v", GL_VERTEX_SHADER)
    frag_shader = compile_shader(f"{shader_folder}/brush_{render_mode}.f", GL_FRAGMENT_SHADER)
    brush_shader = compileProgram(vert_shader, frag_shader)
    glLinkProgram(brush_shader)
    # Titanfall 2 & Apex Legends MESHES
    # mesh_shader
    vert_shader = compile_shader(f"{shader_folder}/mesh.v", GL_VERTEX_SHADER)
    frag_shader = compile_shader(f"{shader_folder}/mesh_{render_mode}.f", GL_FRAGMENT_SHADER)
    mesh_shader = compileProgram(vert_shader, frag_shader)
    glLinkProgram(mesh_shader)
    # debug_mesh_shader
    vert_shader = compile_shader(f"{shader_folder}/mesh_debug.v", GL_VERTEX_SHADER)
    frag_shader = compile_shader(f"{shader_folder}/mesh_debug.f", GL_FRAGMENT_SHADER)
    debug_mesh_shader = compileProgram(vert_shader, frag_shader)
    glLinkProgram(debug_mesh_shader)
    del vert_shader, frag_shader

    if bsp.bsp_version == 20:
        bsp_shader = brush_shader
    else:
        bsp_shader = debug_mesh_shader

    # SHADER VERTEX FORMAT
    # BSP FACES
    glEnableVertexAttribArray(0)  # vertexPosition
    glEnableVertexAttribArray(1)  # vertexNormal
    glEnableVertexAttribArray(2)  # vertexTexcoord
    glEnableVertexAttribArray(3)  # vertexLightmapCoord
    glEnableVertexAttribArray(4)  # reflectivityColour
    glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 52, GLvoidp(0))
    glVertexAttribPointer(1, 3, GL_FLOAT, GL_TRUE,  52, GLvoidp(12))
    glVertexAttribPointer(2, 2, GL_FLOAT, GL_FALSE, 52, GLvoidp(24))
    glVertexAttribPointer(3, 2, GL_FLOAT, GL_FALSE, 52, GLvoidp(32))
    glVertexAttribPointer(4, 3, GL_FLOAT, GL_FALSE, 52, GLvoidp(40))

    # rBSP MESHES
    glEnableVertexAttribArray(5)  # vertexPosition
    glEnableVertexAttribArray(6)  # vertexNormal
    glEnableVertexAttribArray(7)  # vertexTexCoord
    glVertexAttribPointer(5, 3, GL_FLOAT, GL_FALSE, 32, GLvoidp(0))
    glVertexAttribPointer(6, 3, GL_FLOAT, GL_TRUE,  32, GLvoidp(12))
    glVertexAttribPointer(7, 2, GL_FLOAT, GL_FALSE, 32, GLvoidp(24))

    # SHADER UNIFORMS
    ...

    # tracing backwards from a path_track that touches nothing
    # looking at train_watcher / cart for the start would be better
    tracks = dict()
    for entity in bsp.ENTITIES:
        if entity["classname"] == "path_track":
            if "target" not in entity:
                start = entity
                continue
            next_track = entity["target"]  # next path_track
            tracks[next_track] = entity
    payload_track = [start]
    while len(payload_track) < len(tracks):
        current_track = payload_track[-1]["targetname"]  # name of path_track
        payload_track.append(tracks[current_track])  # <<< tracing backwards

    # INPUT STATE
    keys = []
    mousepos = vector.vec2()
    view_init = vector.vec3(0, 0, 32), None, 128
    VIEW_CAMERA = camera.freecam(*view_init)

    # SDL EVENT STATE
    event = SDL_Event()
    SDL_GL_SetSwapInterval(0)
    SDL_CaptureMouse(SDL_TRUE)
    SDL_SetRelativeMouseMode(SDL_TRUE)
    SDL_SetWindowGrab(window, SDL_TRUE)
    SDL_WarpMouseInWindow(window, width // 2, height // 2)

    end_of_previous_tick = time.time()
    tickrate = 120
    while True:
        while SDL_PollEvent(ctypes.byref(event)) != 0:
            if event.type == SDL_QUIT or event.key.keysym.sym == SDLK_ESCAPE and event.type == SDL_KEYDOWN:
                SDL_GL_DeleteContext(glContext)
                SDL_DestroyWindow(window)
                return SDL_Quit()
            if event.type == SDL_KEYDOWN:
                if event.key.keysym.sym not in keys:
                    keys.append(event.key.keysym.sym)
            if event.type == SDL_KEYUP:
                while event.key.keysym.sym in keys:
                    keys.remove(event.key.keysym.sym)
            if event.type == SDL_MOUSEBUTTONDOWN:
                if event.button.button not in keys:
                    keys.append(event.button.button)
            if event.type == SDL_MOUSEBUTTONUP:
                while event.button.button in keys:
                    keys.remove(event.button.button)
            if event.type == SDL_MOUSEMOTION:
                mousepos += vector.vec2(event.motion.xrel, event.motion.yrel)
                SDL_WarpMouseInWindow(window, width // 2, height // 2)
            if event.type == SDL_MOUSEWHEEL:
                VIEW_CAMERA.speed += event.wheel.y * 32

        dt = time.time() - end_of_previous_tick
        while dt >= 1 / tickrate:
            # TICK START
            VIEW_CAMERA.update(mousepos, keys, 1 / tickrate)
            VIEW_CAMERA.speed = max(1, VIEW_CAMERA.speed)
            if SDLK_BACKQUOTE in keys:  # ~: debug print
                print(VIEW_CAMERA)
                while SDLK_BACKQUOTE in keys:  # print once until pressed again
                    keys.remove(SDLK_BACKQUOTE)
            if SDLK_r in keys:  # R: reset camera
                VIEW_CAMERA = camera.freecam(*view_init)
            if SDLK_LSHIFT in keys:  # LShift: Increase camera speed
                VIEW_CAMERA.speed += 5
            if SDLK_LCTRL in keys:  # LCtrl: reduce camera speed
                VIEW_CAMERA.speed -= 5
            # TICK END
            dt -= 1 / tickrate
            end_of_previous_tick = time.time()

        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

        glPushMatrix()
        VIEW_CAMERA.set()
        glUseProgram(bsp_shader)
        glDrawElements(GL_TRIANGLES, len(indices), GL_UNSIGNED_INT, GLvoidp(0))

        # ORIGIN MARKER
        glUseProgram(0)
        glBegin(GL_LINES)
        glColor(1, 0, 0)
        glVertex(0, 0, 0)
        glVertex(128, 0, 0)
        glColor(0, 1, 0)
        glVertex(0, 0, 0)
        glVertex(0, 128, 0)
        glColor(0, 0, 1)
        glVertex(0, 0, 0)
        glVertex(0, 0, 128)
        glEnd()

        # ENTITY ORIGINS
        glColor(1, 0, 1)
        glBegin(GL_POINTS)
        for entity in bsp.ENTITIES:
            if "origin" not in entity:
                continue
            glVertex(*map(float, entity["origin"].split()))
        glEnd()

        # PATH_TRACK CONNECTIONS
        glBegin(GL_LINE_STRIP)
        for path_track in payload_track:
            glVertex(*map(float, path_track["origin"].split()))
        glEnd()

        glPopMatrix()

        SDL_GL_SwapWindow(window)


if __name__ == "__main__":
    bsps = {"E:/Mod/Titanfall/maps/": [],
            "E:/Mod/Titanfall2/maps/": []}

    for folder in bsps:
        bsps[folder] = [f"{mapname}.bsp" for mapname in open(f"{folder}../maplist.txt").readlines()]

    bsps.update({"D:/SteamLibrary/steamapps/common/Team Fortress 2/tf/maps/": ["cp_cloak.bsp",
                                                                               "cp_coldfront.bsp",
                                                                               "pl_upward.bsp"],
                 "E:/Mod/ApexLegends/maps/": ["mp_rr_canyonlands_64k_x_64k.bsp",  # King's Canyon
                                              "mp_rr_desertlands_64k_x_64k.bsp",  # World's Edge
                                              "olympus.bsp"]})

    # folder = "D:/SteamLibrary/steamapps/common/Team Fortress 2/tf/maps/"
    # filename = "cp_cloak.bsp"
    # filename = "cp_coldfront.bsp"
    # folder, filename = "../maps/", "pl_upward.bsp"

    # folder = "E:/Mod/Titanfall/maps/"
    # filename = "mp_angel_city.bsp"

    # folder = "E:/Mod/Titanfall2/maps/"
    # filename = "mp_colony02"
    # filename = "mp_crashsite3"
    # filename = "mp_drydock"
    # filename = "mp_glitch"
    # filename = "mp_lf_uma"
    # filename = "mp_relic02"

    # folder = "E:/Mod/ApexLegends/maps/"
    # filename = "mp_rr_canyonlands_staging.bsp"
    # filename = "mp_rr_canyonlands_mu1_night.bsp"
    # filename = "mp_rr_canyonlands_mu2.bsp"

    width, height = 1280, 720
    for folder in bsps:
        for filename in folder:
            try:
                main(width, height, bsp_tool.load(os.path.join(folder, filename)))
            except Exception as exc:
                SDL_Quit()
                raise exc
