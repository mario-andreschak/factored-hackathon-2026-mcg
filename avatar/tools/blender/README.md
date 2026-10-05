# Local Spark asset pipeline

`build_spark.py` authors an original stylized road mechanic directly in Blender 4.5: sculpted proportions, swept hair, wavy felt hat, brass goggles, feather, canvas jacket, scarf, toolkit, and boots. It imports no meshes or art. Nothing is sent to a cloud renderer.

From the `avatar` directory in PowerShell:

```powershell
& 'C:/Program Files/Blender Foundation/Blender 4.5/blender.exe' --background --factory-startup --python tools/blender/build_spark.py -- (Get-Location).Path
```

This saves:

- `assets/spark/spark.blend`: compressed, editable character and studio scene.
- `assets/spark/preview.png`: 1200px local Cycles portrait, 48 samples with denoising.
- `public/models/spark.glb`: self-contained PBR asset, 20-joint skin, `Idle`, `Talk`, and `Gesture` clips, and `MouthOpen`, `BlinkL`, and `BlinkR` morph targets.

The current GLB is 3.44 MB and uses 25 mesh primitives. Rigid pieces join by material while keeping their bone weights. No Draco decoder, texture downloads, remote rigging service, or asset CDN is required. The initial CPU portrait render took 51 seconds on this workstation; measured cloud render cost is $0. Add `--skip-render` after the avatar directory to rebuild the mesh/rig/export without repeating the portrait render.

`ThreeWorld.tsx` loads the asset only for Spark, blends the three skeletal clips, drives the mouth with the actual audio envelope, blinks, and adds pointer gaze. The previous procedural character stays visible while loading and remains the fallback if loading fails. Hidden tabs pause rendering. Reduced motion freezes body animation while retaining speech mouth movement. Cleanup aborts the asset fetch and disposes geometries, materials, skeletons, and mixer bindings.

`tests/model.test.ts` checks binary integrity, bounded runtime size/draw calls, all skin weights, no external asset URLs, distinct moving clips, and expression targets. The glTF export uses Blender's standard [glTF exporter](https://github.com/KhronosGroup/glTF-Blender-IO/blob/main/docs/blender_docs/scene_gltf2.rst).

Moss's ten hand-painted environments remain separate. A later 3D Moss should be authored as a new character and lit to match those environments; replacing its existing painted face requires an intentional composition pass, not an automatic overlay.
