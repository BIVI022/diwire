import assert from "node:assert/strict";
import {mkdtempSync,mkdirSync,writeFileSync,rmSync,symlinkSync} from "node:fs";
import {join} from "node:path";
import {tmpdir} from "node:os";
import test from "node:test";
import {verifyIndependentReview} from "../automation/merge-gate.mjs";
function fixture() {
  const directory=mkdtempSync(join(tmpdir(),"bb-independent-test-"));
  const base=join(directory,"thread-storage"),caller=join(base,"thr_writer"),reviewer=join(base,"thr_reviewer");
  mkdirSync(caller,{recursive:true});mkdirSync(reviewer,{recursive:true});
  const report={reviewer_thread_id:"thr_reviewer",verdict:"passed",blocking_findings:[],head_sha:"a".repeat(40),base_sha:"b".repeat(40),review_inventory_sha256:"c".repeat(64)};
  const path=join(reviewer,"review.json");writeFileSync(path,JSON.stringify(report));
  const info={thread:{projectId:"proj_hypmgayr8j",status:"idle",providerId:"codex",activeBackgroundAgentCount:0,queuedMessageCount:0}};
  const row={id:"thr_reviewer",activity:{activeWorkflowCount:0,activeBackgroundAgentCount:0,activeBackgroundCommandCount:0,activeGoalCount:0,activePlanModeCount:0}};
  const request=args=>args[1]==="show"?info:[row];
  const context={threadId:"thr_writer",threadStorage:caller};
  return {directory,base,caller,reviewer,path,report,info,row,request,context};
}
test("a real report in canonical storage and an idle reviewer verifies",()=>{
  const f=fixture();try {assert.equal(verifyIndependentReview(f.path,f.request,f.context).verified,true);}
  finally {rmSync(f.directory,{recursive:true,force:true});}
});
test("a reviewer ID embedded under the writer storage is rejected",()=>{
  const f=fixture();try {
    const dir=join(f.caller,"fallback-probe","thr_reviewer");mkdirSync(dir,{recursive:true});
    const path=join(dir,"review.json");writeFileSync(path,JSON.stringify(f.report));
    assert.throws(()=>verifyIndependentReview(path,f.request,f.context),/canonical reviewer storage/);
  } finally {rmSync(f.directory,{recursive:true,force:true});}
});
test("a report symlink that escapes reviewer storage is rejected",()=>{
  const f=fixture();try {
    const outside=join(f.caller,"other.json");writeFileSync(outside,JSON.stringify(f.report));
    const path=join(f.reviewer,"linked.json");symlinkSync(outside,path);
    assert.throws(()=>verifyIndependentReview(path,f.request,f.context),/canonical reviewer storage/);
  } finally {rmSync(f.directory,{recursive:true,force:true});}
});
test("a reviewer storage symlink outside the canonical base is rejected",()=>{
  const f=fixture();try {
    const outside=join(f.directory,"outside");mkdirSync(outside);
    rmSync(f.reviewer,{recursive:true});symlinkSync(outside,f.reviewer,"dir");
    const path=join(f.reviewer,"review.json");writeFileSync(path,JSON.stringify(f.report));
    assert.throws(()=>verifyIndependentReview(path,f.request,f.context),/canonical reviewer storage/);
  } finally {rmSync(f.directory,{recursive:true,force:true});}
});
for(const [label,change] of [
  ["background agent",f=>{f.info.thread.activeBackgroundAgentCount=1;}],
  ["active workflow",f=>{f.row.activity.activeWorkflowCount=1;}],
  ["queued work",f=>{f.info.thread.queuedMessageCount=1;}],
  ["active root",f=>{f.info.thread.status="active";}],
  ["different project",f=>{f.info.thread.projectId="another";}],
]) test(`${label} is not a completed independent review`,()=>{
  const f=fixture();try {change(f);assert.equal(verifyIndependentReview(f.path,f.request,f.context).verified,false);}
  finally {rmSync(f.directory,{recursive:true,force:true});}
});
