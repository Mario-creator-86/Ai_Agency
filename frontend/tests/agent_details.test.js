import test from 'node:test';
import assert from 'node:assert/strict';
import {loadAgentDetails} from '../src/agent_details.js';
function fake(modelId='m',available=true){return async path=>{
 if(path==='/agents/a')return {id:'a',model_id:modelId,provider_id:'p'};
 if(path==='/providers/p/models')return {models:[{id:'m',provider_id:'p',model_name:'configured-model',is_available:available}]};
 if(path==='/providers/')return {providers:[{id:'p',name:'Configured provider'}]};
 throw new Error('Unexpected request');};}
test('inspector resolves the saved assignment without relying on office layout fields',async()=>{
 const result=await loadAgentDetails(fake(),'a');
 assert.equal(result.model_name,'configured-model');assert.equal(result.provider_name,'Configured provider');assert.equal(result.model_is_available,true);
});
test('unverified assignments remain assigned and only explicit empty assignments show none',async()=>{
 assert.equal((await loadAgentDetails(fake('m',false),'a')).model_name,'configured-model');
 assert.equal((await loadAgentDetails(fake('m',false),'a')).model_is_available,false);
 assert.equal((await loadAgentDetails(fake(null),'a')).model_name,null);
});
test('missing fields, missing catalog model and failed requests never mean no model assigned',async()=>{
 await assert.rejects(loadAgentDetails(async()=>({id:'a'}),'a'),/nu includ alocarea/);
 await assert.rejects(loadAgentDetails(fake('absent'),'a'),/nu a fost găsit/);
 await assert.rejects(loadAgentDetails(async()=>{throw new Error('Offline');},'a'),/Offline/);
});
