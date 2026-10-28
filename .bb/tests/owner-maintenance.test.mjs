import assert from "node:assert/strict";
import {createHash} from "node:crypto";
import {mkdtempSync,mkdirSync,writeFileSync,readFileSync,rmSync} from "node:fs";
import {tmpdir} from "node:os";
import {join} from "node:path";
import test from "node:test";
import {verifyOwnerMaintenance} from "../automation/merge-gate.mjs";

function fixture() {
  const root=mkdtempSync(join(tmpdir(),"diwire-owner-maintenance-"));
  const workspace=join(root,"candidate");
  const threadStorage=join(root,"thr_owner");
  mkdirSync(workspace);mkdirSync(threadStorage);
  const verifierPath=join(root,"pinned-verifier.mjs");
  writeFileSync(verifierPath,"// Independently reviewed verifier\n");
  const authorization={kind:"owner_authorized_automation_maintenance",root_thread_id:"thr_owner",owner_request:"Owner requested this exact automation update",verifier_sha256:createHash("sha256").update(readFileSync(verifierPath)).digest("hex")};
  const path=join(threadStorage,"authorization.json");
  const context={threadId:"thr_owner",threadStorage,workspace,verifierPath};
  const run=()=>{writeFileSync(path,JSON.stringify(authorization));return verifyOwnerMaintenance(path,context);};
  return {root,workspace,path,context,authorization,run,close:()=>rmSync(root,{recursive:true,force:true})};
}
test("owner authorization needs a fixed verifier outside the candidate",()=>{
  const f=fixture();try {assert.equal(f.run().verified,true);} finally {f.close();}
});
for(const [name,mutate] of [
  ["another root",f=>{f.authorization.root_thread_id="thr_worker";}],
  ["blank owner request",f=>{f.authorization.owner_request=" ";}],
  ["ordinary daily kind",f=>{f.authorization.kind="daily";}],
  ["changed verifier",f=>{writeFileSync(f.context.verifierPath,"// Changed after review\n");}],
  ["candidate verifier",f=>{f.context.verifierPath=join(f.workspace,"gate.mjs");writeFileSync(f.context.verifierPath,"// Independently reviewed verifier\n");}],
  ["receipt outside root storage",f=>{f.context.threadStorage=f.workspace;}],
]) test(`owner maintenance rejects ${name}`,()=>{
  const f=fixture();try {mutate(f);assert.equal(f.run().verified,false);} finally {f.close();}
});
test("missing root context cannot verify maintenance",()=>{
  const f=fixture();try {
    f.context.threadId="";
    assert.throws(f.run,/root-owned authorization/);
  } finally {f.close();}
});
