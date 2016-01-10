import bpy
import gpu


import itertools
import json
import collections
import base64
import gzip
import struct


if 'imported' in locals():
    import imp
    import bpy
    imp.reload(gpu_luts)
else:
    imported = True
    from . import gpu_luts


EXPORT_SHADERS = True
EMBED_IMAGES = False


class Buffer:
    ARRAY_BUFFER = 34962
    ELEMENT_ARRAY_BUFFER = 34963

    BYTE = 5120
    UNSIGNED_BYTE = 5121
    SHORT = 5122
    UNSIGNED_SHORT = 5123
    FLOAT = 5126

    VEC3 = 'VEC3'
    VEC2 = 'VEC2'
    SCALAR = 'SCALAR'

    class Accessor:
        def __init__(self,
                     name,
                     buffer,
                     buffer_view,
                     byte_offset,
                     byte_stride,
                     component_type,
                     count,
                     type):
            self.name = name
            self.buffer = buffer
            self.buffer_view = buffer_view
            self.byte_offset = byte_offset
            self.byte_stride = byte_stride
            self.component_type = component_type
            self.count = count
            self.type = type

            if self.type == Buffer.VEC3:
                self.type_size = 3
            elif self.type == Buffer.VEC2:
                self.type_size = 2
            else:
                self.type_size = 1

            if component_type == Buffer.BYTE:
                self._ctype = '<b'
            elif component_type == Buffer.UNSIGNED_BYTE:
                self._ctype = '<B'
            elif component_type == Buffer.SHORT:
                self._ctype = '<h'
            elif component_type == Buffer.UNSIGNED_SHORT:
                self._ctype = '<H'
            elif component_type == Buffer.FLOAT:
                self._ctype = '<f'
            else:
                raise ValueError("Bad component type")

            self._ctype_size = struct.calcsize(self._ctype)
            self._buffer_data = self.buffer._get_buffer_data(self.buffer_view)

        # Inlined for performance, leaving this here as reference
        # def _get_ptr(self, idx):
            # addr = ((idx % self.type_size) * self._ctype_size + idx // self.type_size * self.byte_stride) + self.byte_offset
            # return addr

        def __len__(self):
            return self.count

        def __getitem__(self, idx):
            if not isinstance(idx, int):
                raise TypeError("Expected an integer index")

            ptr = ((idx % self.type_size) * self._ctype_size + idx // self.type_size * self.byte_stride) + self.byte_offset

            return struct.unpack_from(self._ctype, self._buffer_data, ptr)[0]

        def __setitem__(self, idx, value):
            if not isinstance(idx, int):
                raise TypeError("Expected an integer index")

            ptr = ((idx % self.type_size) * self._ctype_size + idx // self.type_size * self.byte_stride) + self.byte_offset

            struct.pack_into(self._ctype, self._buffer_data, ptr, value)

    def __init__(self, name, uri=None):
        self.name = '{}_buffer'.format(name)
        self.type = 'arraybuffer'
        self.bytelength = 0
        self.uri = uri
        self.buffer_views = collections.OrderedDict()
        self.accessors = {}

    def export_buffer(self):
        data = bytearray()
        for bn, bv in self.buffer_views.items():
            data.extend(bv['data'])
            #print(bn)

            #if bv['target'] == Buffer.ARRAY_BUFFER:
            #    idx = bv['byteoffset']
            #    while idx < bv['byteoffset'] + bv['bytelength']:
            #    	print(struct.unpack_from('<ffffff', data, idx))
            #    	idx += 24
            #if bv['target'] == Buffer.ELEMENT_ARRAY_BUFFER:
            #    idx = bv['byteoffset']
            #    while idx < bv['byteoffset'] + bv['bytelength']:
            #    	print(struct.unpack_from('<HHH', data, idx))
            #    	idx += 6

        uri = 'data:text/plain;base64,' + base64.b64encode(data).decode('ascii')
        #fname = '{}.bin'.format(self.name)
        #with open(fname, 'wb') as f:
        #    for bv in self.buffer_views.values():
        #    	f.write(bv['data'])

        #uri = 'data:text/plain;base64,'
        #with open(fname, 'rb') as f:
        #    uri += str(base64.b64encode(f.read()), 'ascii')

        return {
            'byteLength': self.bytelength,
            'type': self.type,
            'uri': uri,
        }

    def add_view(self, bytelength, target):
        buffer_name = '{}_view_{}'.format(self.name, len(self.buffer_views))
        self.buffer_views[buffer_name] = {
                'data': bytearray(bytelength),
                'target': target,
                'bytelength': bytelength,
                'byteoffset': self.bytelength,
            }
        self.bytelength += bytelength
        return buffer_name

    def export_views(self):
        gltf = {}

        for k, v in self.buffer_views.items():
            gltf[k] = {
                'buffer': self.name,
                'byteLength': v['bytelength'],
                'byteOffset': v['byteoffset'],
                'target': v['target'],
            }

        return gltf

    def _get_buffer_data(self, buffer_view):
        return self.buffer_views[buffer_view]['data']

    def add_accessor(self,
                     buffer_view,
                     byte_offset,
                     byte_stride,
                     component_type,
                     count,
                     type):
        accessor_name = '{}_accessor_{}'.format(self.name, len(self.accessors))
        self.accessors[accessor_name] = self.Accessor(accessor_name, self, buffer_view, byte_offset, byte_stride, component_type, count, type)
        return self.accessors[accessor_name]

    def export_accessors(self):
        gltf = {}

        for k, v in self.accessors.items():
            gltf[k] = {
                'bufferView': v.buffer_view,
                'byteOffset': v.byte_offset,
                'byteStride': v.byte_stride,
                'componentType': v.component_type,
                'count': v.count,
                'type': v.type,
            }

        return gltf


g_buffers = []


def togl(matrix):
    return [i for col in matrix.col for i in col]


def export_cameras(cameras):
    def export_camera(camera):
        if camera.type == 'ORTHO':
            return {
                'orthographic': {
                    'xmag': camera.ortho_scale,
                    'ymag': camera.ortho_scale,
                    'zfar': camera.clip_end,
                    'znear': camera.clip_start,
                },
                'type': 'orthographic',
            }
        else:
            return {
                'perspective': {
                    'aspectRatio': camera.angle_x / camera.angle_y,
                    'yfov': camera.angle_y,
                    'zfar': camera.clip_end,
                    'znear': camera.clip_start,
                },
                'type': 'perspective',
            }

    return {camera.name: export_camera(camera) for camera in cameras}


def export_materials(materials, shaders, programs, techniques):
    def export_material(material):
        return {
                'values': {
                    'diffuse': list((material.diffuse_color * material.diffuse_intensity)[:]) + [material.alpha],
                    'specular': list((material.specular_color * material.specular_intensity)[:]) + [material.specular_alpha],
                    'shininess': material.specular_hardness,
                    'textures': [ts.texture.name for ts in material.texture_slots if ts and ts.texture.type == 'IMAGE'],
                    'uv_layers': [ts.uv_layer for ts in material.texture_slots if ts]
                }
            }
    exp_materials = {}
    for material in materials:
        if not EXPORT_SHADERS:
            exp_materials[material.name] = export_material(material)
        else:
            # Handle shaders
            shader_data = gpu.export_shader(bpy.context.scene, material)
            fs_bytes = shader_data['fragment'].encode()
            fs_uri = 'data:text/plain;base64,' + base64.b64encode(fs_bytes).decode('ascii')
            shaders[material.name+'FS'] = {'type': 35632, 'uri': fs_uri}
            vs_bytes = shader_data['vertex'].encode()
            vs_uri = 'data:text/plain;base64,' + base64.b64encode(vs_bytes).decode('ascii')
            shaders[material.name+'VS'] = {'type': 35633, 'uri': vs_uri}

            # Handle programs
            programs[material.name+'Program'] = {
                'attributes' : [],
                'fragmentShader' : material.name+'FS',
                'vertexShader' : material.name+'VS',
            }

            # Handle parameters/values
            values = {}
            parameters = {}
            for uniform in shader_data['uniforms']:
                valname = gpu_luts.TYPE_TO_NAME.get(uniform['type'], uniform['varname'])
                rnaname = valname
                semantic = None
                node = None
                value = None

                if uniform['type'] in gpu_luts.LAMP_TYPES:
                    node = uniform['lamp'].name
                    valname = node + '_' + valname
                    semantic = gpu_luts.TYPE_TO_SEMANTIC.get(uniform['type'], None)
                    if not semantic:
                        lamp_obj = bpy.data.objects[node]
                        value = getattr(lamp_obj.data, rnaname)
                elif uniform['type'] in gpu_luts.MIST_TYPES:
                    valname = 'mist_' + valname
                    settings = bpy.context.scene.world.mist_settings
                    if valname == 'mist_color':
                        value = bpy.context.scene.world.horizon_color
                    else:
                        value = getattr(settings, rnaname)

                    if valname == 'mist_falloff':
                        value = 0.0 if value == 'QUADRATIC' else 1.0 if 'LINEAR' else 2.0
                elif uniform['type'] in gpu_luts.WORLD_TYPES:
                    world = bpy.context.scene.world
                    value = getattr(world, rnaname)
                elif uniform['type'] in gpu_luts.MATERIAL_TYPES:
                    value = gpu_luts.DATATYPE_TO_CONVERTER[uniform['datatype']](getattr(material, rnaname))
                    values[valname] = value
                else:
                    print('Unconverted uniform:', uniform)

                parameter = {}
                if semantic:
                    parameter['semantic'] = semantic
                    parameter['node'] = node
                else:
                    parameter['value'] = gpu_luts.DATATYPE_TO_CONVERTER[uniform['datatype']](value)
                parameter['type'] = gpu_luts.DATATYPE_TO_GLTF_TYPE[uniform['datatype']]
                parameters[valname] = parameter
                uniform['valname'] = valname

            # Handle techniques
            tech_name = material.name + 'Technique'
            techniques[tech_name] = {
                'parameters' : parameters,
                'program' : material.name+'Program',
                'attributes' : {a['varname'] : a['varname'] for a in shader_data['attributes']},
                'uniforms' : {u['varname'] : u['valname'] for u in shader_data['uniforms']},
            }

            exp_materials[material.name] = {'technique': tech_name, 'values': values}

    return exp_materials


def export_meshes(meshes):
    def export_mesh(me):
        # glTF data
        gltf_mesh = {
                'name': me.name,
                'primitives': [],
            }

        me.calc_normals_split()
        me.calc_tessface()

        num_loops = len(me.loops)
        num_uv_layers = len(me.uv_layers)
        vertex_size = (3 + 3 + num_uv_layers * 2) * 4

        buf = Buffer(me.name)

        # Vertex data
        va = buf.add_view(vertex_size * num_loops, Buffer.ARRAY_BUFFER)
        vdata = buf.add_accessor(va, 0, vertex_size, Buffer.FLOAT, num_loops, Buffer.VEC3)
        ndata = buf.add_accessor(va, 12, vertex_size, Buffer.FLOAT, num_loops, Buffer.VEC3)
        tdata = [buf.add_accessor(va, 24 + 8 * i, vertex_size, Buffer.FLOAT, num_loops, Buffer.VEC2) for i in range(num_uv_layers)]

        for i, loop in enumerate(me.loops):
            vtx = me.vertices[loop.vertex_index]
            #print('row', i)
            #print('vertex', vtx.co)
            #print('normal', loop.normal)

            co = vtx.co
            normal = loop.normal

            for j in range(3):
                vdata[(i * 3) + j] = co[j]
                ndata[(i * 3) + j] = normal[j]

            for j, uv_layer in enumerate(me.uv_layers):
                tdata[j][i * 2] = uv_layer.data[i].uv.x
                tdata[j][i * 2 + 1] = uv_layer.data[i].uv.y

        prims = {ma.name if ma else '': [] for ma in me.materials}
        if not prims:
            prims = {'': []}

        # Index data
        for poly in me.polygons:
            first = poly.loop_start
            mat = me.materials[poly.material_index]
            prim = prims[mat.name if mat else '']

            if poly.loop_total == 3:
                prim += (first, first + 1, first + 2)
            elif poly.loop_total > 3:
                last = first + poly.loop_total - 1
                for i in range(first, last - 1):
                    prim += (last, i, i + 1)
            else:
                raise RuntimeError("Invalid polygon with {} vertexes.".format(poly.loop_total))

        for mat, prim in prims.items():
            ib = buf.add_view(2 * len(prim), Buffer.ELEMENT_ARRAY_BUFFER)
            idata = buf.add_accessor(ib, 0, 2, Buffer.UNSIGNED_SHORT, len(prim), Buffer.SCALAR)
            for i, v in enumerate(prim):
                idata[i] = v

            gltf_prim = {
                'attributes': {
                    'POSITION': vdata.name,
                    'NORMAL': ndata.name,
                },
                'indices': idata.name,
                'mode': 4,
                'material': mat,
            }
            for i, v in enumerate(tdata):
                gltf_prim['attributes']['TEXCOORD_' + me.uv_layers[i].name] = v.name

            gltf_mesh['primitives'].append(gltf_prim)

        g_buffers.append(buf)
        return gltf_mesh

    return {me.name: export_mesh(me) for me in meshes}


def export_lights(lamps):
    def export_light(light):
        def calc_att():
            kl = 0
            kq = 0

            if light.falloff_type == 'INVERSE_LINEAR':
                kl = 1 / light.distance
            elif light.falloff_type == 'INVERSE_SQUARE':
                kq = 1 / light.distance
            elif light.falloff_type == 'LINEAR_QUADRATIC_WEIGHTED':
                kl = light.linear_attenuation * (1 / light.distance)
                kq = light.quadratic_attenuation * (1 / (light.distance * light.distance))

            return kl, kq

        if light.type == 'SUN':
            return {
                'directional': {
                    'color': (light.color * light.energy)[:],
                },
                'type': 'directional',
            }
        elif light.type == 'POINT':
            kl, kq = calc_att()
            return {
                'point': {
                    'color': (light.color * light.energy)[:],

                    # TODO: grab values from Blender lamps
                    'constantAttenuation': 1,
                    'linearAttenuation': kl,
                    'quadraticAttenuation': kq,
                },
                'type': 'point',
            }
        elif light.type == 'SPOT':
            kl, kq = calc_att()
            return {
                'spot': {
                    'color': (light.color * light.energy)[:],

                    # TODO: grab values from Blender lamps
                    'constantAttenuation': 1.0,
                    'fallOffAngle': 3.14159265,
                    'fallOffExponent': 0.0,
                    'linearAttenuation': kl,
                    'quadraticAttenuation': kq,
                },
                'type': 'spot',
            }
        else:
            print("Unsupported lamp type on {}: {}".format(light.name, light.type))
            return {'type': 'unsupported'}

    gltf = {lamp.name: export_light(lamp) for lamp in lamps}

    return gltf


def export_nodes(objects):
    def export_node(obj):
        ob = {
            'name': obj.name,
            'children': [child.name for child in obj.children],
            'matrix': togl(obj.matrix_world),
        }

        if obj.type == 'MESH':
            ob['meshes'] = [obj.data.name]
        elif obj.type == 'LAMP':
            ob['extras'] = {'light': obj.data.name}
        elif obj.type == 'CAMERA':
            ob['camera'] = obj.data.name
        elif obj.type == 'EMPTY' and obj.dupli_group is not None:
            # Expand dupli-groups
            ob['children'] += [i.name for i in obj.dupli_group.objects]

        return ob

    return {obj.name: export_node(obj) for obj in objects}


def export_scenes(scenes):
    def export_scene(scene):
        return {
            'nodes': [ob.name for ob in scene.objects],
            'extras': {
                'background_color': scene.world.horizon_color[:],
                'active_camera': scene.camera.name,
                'hidden_nodes': [ob.name for ob in scene.objects if not ob.is_visible(scene)]
            }
        }

    return {scene.name: export_scene(scene) for scene in scenes}


def export_buffers():
    gltf = {
        'buffers': {},
        'bufferViews': {},
        'accessors': {},
    }

    for buf in g_buffers:
        gltf['buffers'][buf.name] = buf.export_buffer()
        gltf['bufferViews'].update(buf.export_views())
        gltf['accessors'].update(buf.export_accessors())

    return gltf


def export_images(images):
    def export_image(image):
        if EMBED_IMAGES:
            pixels = bytearray([int(p * 255) for p in image.pixels])
            uri = 'data:text/plain;base64,' + base64.b64encode(pixels).decode('ascii')
        else:
            uri = image.filepath.replace('//', '')

        return {
            'uri': uri,
        }
    return {image.name: export_image(image) for image in images}


def export_textures(textures):
    def export_texture(texture):
        return {
            'sampler' : 'default',
            'source' : texture.image.name,
        }
    return {texture.name: export_texture(texture) for texture in textures
        if type(texture) == bpy.types.ImageTexture}


def export_gltf(scene_delta):
    global g_buffers

    shaders = {}
    programs = {}
    techniques = {}

    gltf = {
        'asset': {'version': '1.0'},
        'cameras': export_cameras(scene_delta.get('cameras', [])),
        'extras': {'lights' : export_lights(scene_delta.get('lamps', []))},
        'images': export_images(scene_delta.get('images', [])),
        'materials': export_materials(scene_delta.get('materials', []),
            shaders, programs, techniques),
        'meshes': export_meshes(scene_delta.get('meshes', [])),
        'nodes': export_nodes(scene_delta.get('objects', [])),
        'programs': programs,
        'samplers': {'default':{}},
        'scene': bpy.context.scene.name,
        'scenes': export_scenes(scene_delta.get('scenes', [])),
        'shaders': shaders,
        'techniques': techniques,
        'textures': export_textures(scene_delta.get('textures', [])),

        # TODO
        'animations': {},
        'skins': {},
    }

    gltf.update(export_buffers())
    g_buffers = []

    gltf = {key: value for key, value in gltf.items() if value}

    return gltf


if __name__ == '__main__':
    with open('dump.gltf', 'w') as f:
        json.dump(export_gltf, f, indent=4)
