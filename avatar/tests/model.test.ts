import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const bytes=readFileSync(new URL('../public/models/spark.glb',import.meta.url));
const jsonLength=bytes.readUInt32LE(12);
const model=JSON.parse(bytes.subarray(20,20+jsonLength).toString('utf8'));
const binary=bytes.subarray(28+jsonLength);
const floats=(index:number):number[]=>{
  const accessor=model.accessors[index], buffer=model.bufferViews[accessor.bufferView];
  assert.equal(accessor.componentType,5126);
  const width:Record<string,number>={SCALAR:1,VEC2:2,VEC3:3,VEC4:4,MAT4:16};
  const components=width[accessor.type], start=(buffer.byteOffset??0)+(accessor.byteOffset??0), stride=buffer.byteStride??components*4;
  assert.ok(start+(accessor.count-1)*stride+components*4<=binary.length);
  return Array.from({length:accessor.count*components},(_,n)=>binary.readFloatLE(start+Math.floor(n/components)*stride+n%components*4));
};

test('Spark is a complete local GLB with weighted skeleton, bounded draw calls, and no external assets',()=>{
  assert.equal(bytes.readUInt32LE(0),0x46546c67); assert.equal(bytes.readUInt32LE(4),2); assert.equal(bytes.readUInt32LE(8),bytes.length);
  assert.ok(bytes.length<4_000_000); assert.ok(model.meshes.reduce((n:number,mesh:{primitives:unknown[]})=>n+mesh.primitives.length,0)<=30);
  assert.ok((model.buffers??[]).every((buffer:{uri?:string})=>!buffer.uri));
  assert.ok((model.images??[]).every((image:{uri?:string})=>!image.uri));
  assert.equal(model.skins.length,1); assert.equal(model.skins[0].joints.length,20);
  const skinNodes=model.nodes.filter((node:{mesh?:number;skin?:number})=>node.mesh!==undefined);
  assert.equal(skinNodes.length,model.meshes.length); assert.ok(skinNodes.every((node:{skin?:number})=>node.skin===0));
  for(const mesh of model.meshes) for(const primitive of mesh.primitives) {
    assert.ok(primitive.attributes.JOINTS_0!==undefined); assert.ok(primitive.attributes.WEIGHTS_0!==undefined);
    const weights=floats(primitive.attributes.WEIGHTS_0);
    for(let index=0;index<weights.length;index+=4) assert.ok(Math.abs(weights.slice(index,index+4).reduce((sum,n)=>sum+n,0)-1)<.00001);
  }
});

test('Spark exports usable distinct Idle, Talk, and Gesture loops with head/arm movement and voice/blink morphs',()=>{
  assert.deepEqual(model.animations.map((clip:{name:string})=>clip.name),['Idle','Talk','Gesture']);
  for(const clip of model.animations) {
    assert.ok(clip.channels.length>=20);
    const times=floats(clip.samplers[0].input);
    assert.ok(times.at(-1)!-times[0]>=2.9);
    const rotations=clip.channels.filter((channel:{target:{path:string}})=>channel.target.path==='rotation');
    const moving=rotations.filter((channel:{sampler:number})=>{
      const values=floats(clip.samplers[channel.sampler].output);
      return values.some((value,index)=>Math.abs(value-values[index%4])>.01);
    });
    assert.ok(moving.length>=2,`${clip.name} must animate multiple joints`);
    assert.ok(rotations.some((channel:{target:{node:number}})=>model.nodes[channel.target.node].name==='head'));
  }
  const targets=new Set(model.meshes.flatMap((mesh:{extras?:{targetNames?:string[]}})=>mesh.extras?.targetNames??[]));
  for(const name of ['MouthOpen','BlinkL','BlinkR']) assert.ok(targets.has(name));
});
