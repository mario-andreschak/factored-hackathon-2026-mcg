"""Build an original, editable, rigged Spark locally in Blender 4.5.

Run: blender --background --python tools/blender/build_spark.py -- <avatar-dir>
No network, external meshes, raster generation, or cloud compute is used.
"""
from pathlib import Path
import bpy
import math
import sys
from mathutils import Vector

ROOT = Path(sys.argv[sys.argv.index('--') + 1]).resolve()
ASSETS = ROOT / 'assets' / 'spark'
MODELS = ROOT / 'public' / 'models'
ASSETS.mkdir(parents=True, exist_ok=True)
MODELS.mkdir(parents=True, exist_ok=True)
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
scene = bpy.context.scene
scene.render.engine = 'CYCLES'
scene.cycles.samples = 48
scene.cycles.use_denoising = True
scene.render.resolution_x = 1200
scene.render.resolution_y = 1200
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = 'PNG'
scene.render.film_transparent = False
scene.render.fps = 24
scene.view_settings.view_transform = 'AgX'
scene.world.color = (.035, .022, .018)
asset_objects = []
bindings = []

def material(name, color, roughness=.5, metal=0):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*color, 1)
    mat.use_nodes = True
    shader = mat.node_tree.nodes.get('Principled BSDF')
    shader.inputs['Base Color'].default_value = (*color, 1)
    shader.inputs['Roughness'].default_value = roughness
    shader.inputs['Metallic'].default_value = metal
    return mat

skin = material('Warm terracotta skin', (.66, .32, .17), .46)
skin_light = material('Warm lip and ears', (.72, .34, .22), .5)
jacket = material('Worn vermilion canvas', (.42, .065, .033), .72)
jacket_dark = material('Canvas cuffs and seam', (.21, .031, .020), .8)
shirt = material('Cream cotton', (.81, .65, .39), .87)
scarf = material('Petrol blue silk', (.023, .20, .21), .38)
scarf_dark = material('Petrol blue fold', (.012, .083, .10), .65)
trousers = material('Indigo work trousers', (.035, .06, .09), .82)
leather = material('Coffee leather', (.075, .025, .009), .56)
hat_mat = material('Sunburnt ochre felt', (.43, .23, .055), .83)
hat_edge = material('Golden felt edge', (.60, .34, .095), .76)
hair = material('Espresso swept hair', (.027, .009, .005), .47)
metal = material('Aged brass', (.57, .34, .09), .26, .76)
eye_white = material('Ivory eyes', (.96, .91, .74), .25)
iris = material('Amber iris', (.32, .125, .013), .25)
pupil = material('Deep brown pupils', (.004, .002, .001), .19)
mouth_mat = material('Mouth interior', (.032, .004, .003), .86)
teeth_mat = material('Warm teeth', (.94, .84, .64), .44)
sole_mat = material('Boot soles', (.021, .018, .017), .84)

def finish(obj, name, mat, bone='head'):
    obj.name = name
    obj.data.materials.append(mat)
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    asset_objects.append(obj)
    bindings.append((obj, bone))
    return obj

def sphere(name, location, scale, mat, bone='head', segments=32, rings=20):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=segments, ring_count=rings, location=location)
    obj = bpy.context.object
    obj.scale = scale
    return finish(obj, name, mat, bone)

def cube(name, location, scale, mat, bone='head', bevel=.04, rotation=(0,0,0)):
    bpy.ops.mesh.primitive_cube_add(size=1, location=location)
    obj = bpy.context.object
    obj.scale = scale
    obj.rotation_euler = rotation
    obj.name = name
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    modifier = obj.modifiers.new('Soft sewn edges', 'BEVEL')
    modifier.width = bevel
    modifier.segments = 3
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    return finish(obj, name, mat, bone)

def cylinder(name, a, b, radius, mat, bone='head', top=None, vertices=24):
    a, b = Vector(a), Vector(b)
    bpy.ops.mesh.primitive_cone_add(vertices=vertices, radius1=radius, radius2=radius if top is None else top, depth=(b-a).length, location=(a+b)/2)
    obj=bpy.context.object
    obj.rotation_euler = (b-a).to_track_quat('Z','Y').to_euler()
    return finish(obj,name,mat,bone)

def curve(name, points, radius, mat, bone='head'):
    data=bpy.data.curves.new(name,'CURVE')
    data.dimensions='3D'
    data.resolution_u=12
    data.bevel_depth=radius
    data.bevel_resolution=3
    spline=data.splines.new('BEZIER')
    spline.bezier_points.add(len(points)-1)
    for point, position in zip(spline.bezier_points,points):
        point.co=position
        point.handle_left_type='AUTO'
        point.handle_right_type='AUTO'
    obj=bpy.data.objects.new(name,data)
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.objects.active=obj
    obj.select_set(True)
    bpy.ops.object.convert(target='MESH')
    obj=bpy.context.object
    obj.select_set(False)
    return finish(obj,name,mat,bone)

def torus(name, location, major, minor, mat, bone='head', scale=(1,1,1), rotation=(0,0,0)):
    bpy.ops.mesh.primitive_torus_add(major_segments=40,minor_segments=10,location=location,major_radius=major,minor_radius=minor)
    obj=bpy.context.object
    obj.scale=scale
    obj.rotation_euler=rotation
    return finish(obj,name,mat,bone)

# Tailored body silhouette: boots, articulated legs, waist, jacket, scarf.
for side, direction in [('L',1),('R',-1)]:
    x=direction*.235
    sphere('Boot '+side,(x,-.10,.17),(.22,.38,.16),leather,'foot.'+side)
    sphere('Sole '+side,(x,-.10,.072),(.228,.385,.065),sole_mat,'foot.'+side)
    cylinder('Boot shaft '+side,(x,0,.15),(x,0,.44),.17,leather,'shin.'+side,top=.14)
    torus('Boot cuff '+side,(x,0,.41),.143,.016,metal,'shin.'+side)
    cylinder('Trouser calf '+side,(x,0,.37),(x,.015,.73),.135,trousers,'shin.'+side,top=.16)
    cylinder('Trouser thigh '+side,(x,.015,.7),(direction*.21,0,1.16),.16,trousers,'thigh.'+side,top=.19)
    curve('Trouser seam '+side,[(x+direction*.13,-.06,.43),(x+direction*.16,-.045,.72),(x+direction*.15,-.04,1.06)],.008,jacket_dark,'thigh.'+side)

sphere('Jacket body',(0,0,1.43),(.47,.32,.55),jacket,'spine')
sphere('Waist hem',(0,0,.99),(.39,.27,.115),jacket_dark,'pelvis')
cube('Cotton shirt',(0,-.285,1.63),(.31,.055,.42),shirt,'chest',.05)
cube('Jacket zip',(0,-.318,1.29),(.025,.018,.53),metal,'spine',.008)
for direction in [-1,1]:
    collar=cube('Folded jacket lapel '+str(direction),(direction*.19,-.32,1.73),(.145,.07,.33),jacket_dark,'chest',.045,(0,direction*.34,0))
    cube('Breast pocket '+str(direction),(direction*.27,-.305,1.43),(.19,.05,.16),jacket_dark,'chest',.025)
    cube('Pocket flap '+str(direction),(direction*.27,-.338,1.49),(.20,.025,.052),jacket,'chest',.015)
    sphere('Pocket button '+str(direction),(direction*.27,-.36,1.48),(.018,.012,.018),metal,'chest',16,10)
    for index in range(6):
        sphere('Pocket stitch',(direction*.19+direction*index*.028,-.342,1.362),(.005,.004,.004),shirt,'chest',8,6)

sphere('Scarf collar',(0,-.014,1.93),(.36,.31,.105),scarf,'chest')
sphere('Scarf knot',(.14,-.285,1.86),(.12,.10,.095),scarf,'chest')
cube('Scarf hanging tail',(.23,-.30,1.62),(.145,.045,.46),scarf,'scarf',.025,(0,-.16,.10))
curve('Scarf fold',[(.22,-.33,1.85),(.20,-.34,1.64),(.17,-.32,1.40)],.013,scarf_dark,'scarf')
cube('Belt',(0,-.285,1.0),(.72,.045,.085),leather,'pelvis',.03)
cube('Belt buckle',(0,-.318,1.0),(.12,.028,.094),metal,'pelvis',.025)
cube('Small road toolkit',(.43,-.06,1.03),(.17,.21,.23),leather,'pelvis',.04)
for index in range(3):
    cylinder('Tool handle',(.43+(index-1)*.05,-.055,1.08),(.43+(index-1)*.05,-.055,1.23),.013,metal,'pelvis')

for side, direction in [('L',1),('R',-1)]:
    shoulder=(direction*.44,0,1.78)
    elbow=(direction*.77,-.01,1.32)
    wrist=(direction*.87,-.10,1.02)
    cylinder('Jacket sleeve '+side,shoulder,elbow,.19,jacket,'arm.'+side,top=.155)
    sphere('Sleeve shoulder '+side,shoulder,(.22,.22,.23),jacket,'arm.'+side)
    sphere('Soft elbow '+side,elbow,(.16,.17,.17),jacket,'forearm.'+side)
    cylinder('Forearm canvas '+side,elbow,wrist,.153,jacket,'forearm.'+side,top=.12)
    sphere('Jacket cuff '+side,wrist,(.135,.145,.085),jacket_dark,'forearm.'+side)
    sphere('Hand palm '+side,(direction*.90,-.12,.88),(.135,.10,.16),skin,'hand.'+side)
    for finger in range(4):
        x=direction*(.812+finger*.057)
        z=.77-abs(finger-1.5)*.022
        cylinder('Finger '+side+str(finger),(x,-.17,.88),(x,-.19,z),.025,skin,'hand.'+side,top=.020,vertices=12)
        sphere('Fingertip '+side+str(finger),(x,-.19,z),(.021,.024,.034),skin,'hand.'+side,12,8)
    sphere('Thumb '+side,(direction*.79,-.16,.92),(.07,.057,.082),skin,'hand.'+side,20,12)

cylinder('Neck',(0,0,1.82),(0,0,2.17),.20,skin,'neck',top=.22)
head=sphere('Spark face',(0,0,2.62),(.80,.60,.82),skin,'head',48,32)
# Sculpt the chin and cheeks directly in the original mesh, retaining clean UV topology.
for vertex in head.data.vertices:
    z=vertex.co.z/.82
    if z < -.18: vertex.co.x *= 1 - max(0,-z-.18)*.24
    if vertex.co.y < 0:
        vertex.co.y *= .97
        vertex.co.y -= .015*math.exp(-((vertex.co.z+.14)/.25)**2)
head.shape_key_add(name='Basis')
opening=head.shape_key_add(name='MouthOpen')
for vertex, basis in zip(opening.data,head.data.vertices):
    x,y,z=basis.co
    influence=math.exp(-((x/.34)**2+((z+.34)/.24)**2))*max(0,-y/.60)
    vertex.co.z -= influence*.105
    vertex.co.y -= influence*.014

for direction, side in [(-1,'R'),(1,'L')]:
    ear=sphere('Ear '+side,(direction*.755,.015,2.58),(.14,.105,.23),skin_light,'head')
    sphere('Ear hollow '+side,(direction*.81,-.073,2.59),(.047,.028,.11),skin,'head',20,12)
    eye=sphere('Eye white '+side,(direction*.286,-.562,2.72),(.207,.105,.228),eye_white,'head')
    eye.shape_key_add(name='Basis')
    blink=eye.shape_key_add(name='Blink'+side)
    for vertex in blink.data: vertex.co.z *= .075
    sphere('Iris '+side,(direction*.281,-.654,2.70),(.096,.035,.112),iris,'head',28,16)
    sphere('Pupil '+side,(direction*.278,-.683,2.70),(.047,.018,.078),pupil,'head',24,14)
    sphere('Eye glint '+side,(direction*.278-.019,-.70,2.745),(.022,.009,.025),eye_white,'head',16,10)
    curve('Upper eyelid '+side,[(direction*.475,-.583,2.77),(direction*.30,-.629,2.937),(direction*.105,-.590,2.77)],.022,skin_light,'head')
    curve('Eyebrow '+side,[(direction*.47,-.51,3.0),(direction*.30,-.555,3.085+direction*.035),(direction*.13,-.54,3.035)],.038,hair,'head')

sphere('Nose bridge',(0,-.573,2.62),(.103,.12,.23),skin,'head')
sphere('Nose tip',(.018,-.684,2.48),(.133,.14,.105),skin_light,'head')
for direction in [-1,1]: sphere('Nostril',(direction*.079,-.731,2.439),(.025,.025,.011),leather,'head',12,8)
sphere('Cheek left',(.48,-.417,2.43),(.20,.105,.13),skin_light,'head')
sphere('Cheek right',(-.48,-.417,2.43),(.20,.105,.13),skin_light,'head')
mouth=sphere('Speaking mouth',(.045,-.535,2.24),(.25,.052,.056),mouth_mat,'head',32,20)
mouth.shape_key_add(name='Basis')
open_mouth=mouth.shape_key_add(name='MouthOpen')
for vertex in open_mouth.data:
    vertex.co.z *= 3.5
    vertex.co.z -= .054
cube('Upper teeth',(.044,-.588,2.269),(.33,.024,.046),teeth_mat,'head',.015,(0,-.045,0))
curve('Lower smile lip',[(-.17,-.526,2.219),(.04,-.562,2.19),(.27,-.515,2.233)],.018,skin_light,'jaw')
curve('Smile crease left',[(-.19,-.525,2.24),(-.26,-.489,2.30),(-.29,-.48,2.33)],.010,leather,'head')
curve('Smile crease right',[(.28,-.50,2.26),(.34,-.48,2.32)],.010,leather,'head')

# Carefully swept hair clumps, framing the face beneath a tilted road hat.
sphere('Hair cap',(0,.10,3.10),(.76,.52,.33),hair,'head')
for index in range(9):
    x=(index-4)*.13
    curve('Swept hair strand '+str(index),[(x+.18,.13,3.32),(x+.08,-.31,3.22),(x-.08,-.47,3.10)],.052+(index%3)*.012,hair,'head')
for direction in [-1,1]:
    curve('Sideburn '+str(direction),[(direction*.64,-.19,3.08),(direction*.72,-.12,2.84),(direction*.67,-.18,2.61)],.049,hair,'head')

# Wavy hand-shaped brim; unlike a scaled sphere, this reads as a thin felt surface.
vertices=[]
faces=[]
segments=72
for ring in range(3):
    radius=[.42,.91,1.17][ring]
    for index in range(segments):
        angle=index*2*math.pi/segments
        x=math.cos(angle)*radius
        y=math.sin(angle)*radius*.80
        z=3.28
        z += .065*math.cos(angle)+.09*math.sin(angle)**2*(ring/2)+.065*math.cos(angle*2)*(ring/2)
        vertices.append((x,y,z))
for ring in range(2):
    for index in range(segments):
        nxt=(index+1)%segments
        faces.append((ring*segments+index,ring*segments+nxt,(ring+1)*segments+nxt,(ring+1)*segments+index))
data=bpy.data.meshes.new('Hand shaped felt brim')
data.from_pydata(vertices,[],faces)
obj=bpy.data.objects.new('Wavy road hat brim',data)
bpy.context.collection.objects.link(obj)
bpy.context.view_layer.objects.active=obj
obj.select_set(True)
solid=obj.modifiers.new('Felt thickness','SOLIDIFY'); solid.thickness=.035
bpy.ops.object.modifier_apply(modifier=solid.name)
bevel=obj.modifiers.new('Soft felt edge','BEVEL'); bevel.width=.025; bevel.segments=3
bpy.ops.object.modifier_apply(modifier=bevel.name)
finish(obj,obj.name,hat_mat,'head')
curve('Rolled hat edge',[(math.cos(i*2*math.pi/segments)*1.17,math.sin(i*2*math.pi/segments)*1.17*.80,3.28+.065*math.cos(i*2*math.pi/segments)+.09*math.sin(i*2*math.pi/segments)**2+.065*math.cos(i*4*math.pi/segments)) for i in range(segments+1)],.018,hat_edge,'head')
cylinder('Hat crown',(0,0,3.29),(.045,.03,3.82),.53,hat_mat,'head',top=.46,vertices=48)
sphere('Hat crown soft top',(.045,.03,3.81),(.46,.46,.10),hat_mat,'head',40,20)
cylinder('Leather hat band',(0,0,3.29),(.006,.006,3.42),.542,leather,'head',top=.527,vertices=48)
# Brass goggles sit on the band, keeping Spark's eyes expressive and uncovered.
for direction in [-1,1]:
    torus('Goggle frame '+str(direction),(direction*.22,-.481,3.48),.135,.023,metal,'head',rotation=(math.pi/2,0,0))
    sphere('Goggle lens '+str(direction),(direction*.22,-.483,3.48),(.112,.015,.112),scarf_dark,'head',28,18)
    curve('Goggle glint '+str(direction),[(direction*.22-.06,-.50,3.52),(direction*.22-.03,-.506,3.55)],.008,metal,'head')
cube('Goggle bridge',(0,-.499,3.48),(.15,.025,.024),metal,'head',.008)
curve('Hat feather quill',[(.46,-.02,3.48),(.73,.0,3.76),(.79,.02,3.99)],.011,metal,'head')
for index in range(7):
    z=3.60+index*.052
    sphere('Teal feather '+str(index),(.60+index*.03,.015,z),(.12,.017,.057),scarf,'head',20,12)
torus('Ear ring',(-.81,-.038,2.40),.067,.014,metal,'head',rotation=(math.pi/2,0,0))

for obj in asset_objects:
    if obj.name.startswith(('Iris ','Pupil ','Eye glint ')):
        obj.shape_key_add(name='Basis')
        blink=obj.shape_key_add(name='Blink'+obj.name[-1])
        for vertex in blink.data: vertex.co.z *= .075

# Genuine exported skeleton, with skin weights for every visible character mesh.
bpy.ops.object.armature_add(enter_editmode=True, location=(0,0,0))
rig=bpy.context.object
rig.name='Spark_Rig'
rig.data.name='Spark editable humanoid skeleton'
for bone in list(rig.data.edit_bones): rig.data.edit_bones.remove(bone)
specs=[
    ('root',(0,0,0),(0,0,.35),None),
    ('pelvis',(0,0,.86),(0,0,1.18),'root'),
    ('spine',(0,0,1.18),(0,0,1.63),'pelvis'),
    ('chest',(0,0,1.63),(0,0,1.93),'spine'),
    ('neck',(0,0,1.93),(0,0,2.15),'chest'),
    ('head',(0,0,2.15),(0,0,3.1),'neck'),
    ('jaw',(0,-.1,2.35),(0,-.4,2.16),'head'),
    ('scarf',(.14,-.25,1.87),(.22,-.31,1.39),'chest'),
]
for side, direction in [('L',1),('R',-1)]:
    specs += [
        ('arm.'+side,(direction*.43,0,1.78),(direction*.77,-.01,1.32),'chest'),
        ('forearm.'+side,(direction*.77,-.01,1.32),(direction*.87,-.1,1.02),'arm.'+side),
        ('hand.'+side,(direction*.87,-.1,1.02),(direction*.90,-.12,.76),'forearm.'+side),
        ('thigh.'+side,(direction*.21,0,1.14),(direction*.235,.015,.73),'pelvis'),
        ('shin.'+side,(direction*.235,.015,.73),(direction*.235,0,.37),'thigh.'+side),
        ('foot.'+side,(direction*.235,0,.37),(direction*.235,-.24,.12),'shin.'+side),
    ]
for name,start,end,parent in specs:
    bone=rig.data.edit_bones.new(name)
    bone.head=start; bone.tail=end
    if parent: bone.parent=rig.data.edit_bones[parent]
bpy.ops.object.mode_set(mode='OBJECT')
rig.show_in_front=True
asset_objects.append(rig)
for obj,bone_name in bindings:
    group=obj.vertex_groups.new(name=bone_name)
    group.add(list(range(len(obj.data.vertices))),1,'REPLACE')
    modifier=obj.modifiers.new('Spark deformation rig','ARMATURE')
    modifier.object=rig
    obj.parent=rig
for bone in rig.pose.bones: bone.rotation_mode='XYZ'

rig.animation_data_create()
for name,length in [('Idle',96),('Talk',72),('Gesture',96)]:
    action=bpy.data.actions.new(name)
    rig.animation_data.action=action
    for frame in range(1,length+2,4):
        t=(frame-1)/length*math.pi*2
        for bone in rig.pose.bones:
            bone.rotation_euler=(0,0,0); bone.location=(0,0,0); bone.scale=(1,1,1)
        rig.pose.bones['spine'].rotation_euler=(.017*math.sin(t),.025*math.sin(t),.016*math.sin(t))
        rig.pose.bones['root'].location.z=.013*math.sin(t)
        rig.pose.bones['head'].rotation_euler=(.016*math.sin(t+1),.03*math.sin(t),-.035*math.sin(t*.5))
        rig.pose.bones['scarf'].rotation_euler=(.02*math.sin(t),.05*math.sin(t),.035*math.cos(t))
        if name=='Talk':
            rig.pose.bones['head'].rotation_euler=(.04*math.sin(t*2),.06*math.sin(t*1.0),.07*math.sin(t))
            rig.pose.bones['arm.L'].rotation_euler=(.11*math.sin(t),.15*math.cos(t),-.14+.18*math.sin(t*2))
            rig.pose.bones['arm.R'].rotation_euler=(.06*math.cos(t),-.12*math.sin(t),.13+.12*math.cos(t*2))
            rig.pose.bones['forearm.L'].rotation_euler=(.15+.20*math.sin(t),0,0)
            rig.pose.bones['forearm.R'].rotation_euler=(.10+.17*math.cos(t),0,0)
            rig.pose.bones['hand.L'].rotation_euler=(0,.09*math.sin(t*2),.12*math.sin(t*3))
            rig.pose.bones['scarf'].rotation_euler.z=.08*math.sin(t*2)
        elif name=='Gesture':
            emphasis=math.sin(t*.5)**2
            rig.pose.bones['arm.R'].rotation_euler=(.28*emphasis,-.23*emphasis,1.02*emphasis)
            rig.pose.bones['forearm.R'].rotation_euler=(.45*emphasis,0,-.22*emphasis)
            rig.pose.bones['hand.R'].rotation_euler=(0,.20*math.sin(t),-.16*emphasis)
            rig.pose.bones['head'].rotation_euler=(.045*math.sin(t),.13*emphasis,.07*emphasis)
            rig.pose.bones['spine'].rotation_euler.z=-.075*emphasis
        for bone in rig.pose.bones:
            bone.keyframe_insert('rotation_euler',frame=frame,group=bone.name)
            if bone.name=='root': bone.keyframe_insert('location',frame=frame,group=bone.name)
    track=rig.animation_data.nla_tracks.new(); track.name=name
    track.strips.new(name,1,action)
    track.mute=True
rig.animation_data.action=None
for bone in rig.pose.bones:
    bone.rotation_euler=(0,0,0); bone.location=(0,0,0)
scene.frame_set(1)

# Merge rigid skin pieces by material. Vertex groups survive Blender's join,
# retaining the skeleton while avoiding a draw call for every button/finger.
groups={}
for obj in asset_objects:
    if obj.type=='MESH' and not obj.data.shape_keys:
        groups.setdefault(obj.data.materials[0].name,[]).append(obj)
for name, objects in groups.items():
    if len(objects)<2: continue
    bpy.ops.object.select_all(action='DESELECT')
    for obj in objects: obj.select_set(True)
    bpy.context.view_layer.objects.active=objects[0]
    bpy.ops.object.join()
    objects[0].name='Spark '+name
asset_objects=[obj for obj in bpy.data.objects if obj.type=='MESH' and obj.parent==rig]+[rig]

# GLB excludes studio floor, lights, camera; ordinary PBR requires no runtime decoder.
bpy.ops.object.select_all(action='DESELECT')
for obj in asset_objects: obj.select_set(True)
bpy.context.view_layer.objects.active=rig
bpy.ops.export_scene.gltf(filepath=str(MODELS/'spark.glb'),export_format='GLB',use_selection=True,
    export_animations=True,export_animation_mode='NLA_TRACKS',export_frame_range=False,
    export_force_sampling=True,export_skins=True,export_morph=True,export_morph_animation=False,
    export_materials='EXPORT',export_yup=True,export_extras=True,export_optimize_animation_size=True)

# Editable studio scene and a polished local preview; CPU Cycles keeps setup portable.
bpy.ops.object.select_all(action='DESELECT')
bpy.ops.mesh.primitive_plane_add(size=200,location=(0,0,-.007))
floor=bpy.context.object
floor.name='Preview studio floor (not exported)'
floor.data.materials.append(material('Studio clay',(.075,.037,.022),.91))
world=bpy.data.worlds.new('Warm studio')
world.use_nodes=True
world.node_tree.nodes['Background'].inputs[0].default_value=(.19,.12,.08,1)
world.node_tree.nodes['Background'].inputs[1].default_value=.30
scene.world=world
def area(name,location,power,color,size,target=(0,0,2)):
    data=bpy.data.lights.new(name,'AREA'); data.energy=power; data.color=color; data.shape='DISK'; data.size=size
    obj=bpy.data.objects.new(name,data); bpy.context.collection.objects.link(obj)
    obj.location=location; obj.rotation_euler=(Vector(target)-obj.location).to_track_quat('-Z','Y').to_euler()
area('Large warm key',(-4,-5,7),950,(1,.76,.52),5)
area('Soft front fill',(4,-3,4),450,(.50,.73,1),4)
area('Golden rim',(1,3,5),1250,(1,.44,.17),3)
data=bpy.data.cameras.new('Spark preview portrait')
camera=bpy.data.objects.new('Spark preview portrait',data); bpy.context.collection.objects.link(camera)
camera.location=(5.2,-10.2,4.35)
camera.rotation_euler=(Vector((0,0,1.95))-camera.location).to_track_quat('-Z','Y').to_euler()
data.type='ORTHO'; data.ortho_scale=4.65
scene.camera=camera
scene.render.filepath=str(ASSETS/'preview.png')
rig['creator']='Original character authored for Elsewhere. No imported meshes or copied film character.'
rig['clips']='Idle, Talk, Gesture; runtime mouthOpen and BlinkL/BlinkR morph targets'
bpy.ops.wm.save_as_mainfile(filepath=str(ASSETS/'spark.blend'),compress=True)
if '--skip-render' not in sys.argv: bpy.ops.render.render(write_still=True)
print('SPARK_COMPLETE: '+str(MODELS/'spark.glb'))
