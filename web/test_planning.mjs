import assert from'node:assert/strict';
import{band,plan,groundedExplanation}from'./dist/planning.mjs';
for(const[v,b]of[[0,'free'],[40,'free'],[40.1,'light'],[50,'medium'],[60,'crowded'],[70,'very_crowded']])assert.equal(band(v),b);
assert.equal(plan([420,210],6).needed,11);assert.equal(plan([420],6).extra,5);assert.equal(plan([420],0).band,'no_service');assert.throws(()=>plan([420],2.5));assert.throws(()=>plan([-1],6));
const r={sections:[{id:'S',from_name:'A',to_name:'B'}],missing_destination_share:.6,profile:{weekday:{18:{S:420}}}};
const text=groundedExplanation(r,'weekday',18,6);assert.match(text,/420/);assert.match(text,/60%/);assert.match(text,/assumption/);
console.log('Frontend thresholds, arithmetic, invalid inputs and grounded explanations passed.');
