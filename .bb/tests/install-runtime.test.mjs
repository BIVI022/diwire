import assert from "node:assert/strict";
import {execFileSync} from "node:child_process";
import {mkdtempSync, mkdirSync, readFileSync, writeFileSync, rmSync, existsSync} from "node:fs";
import {tmpdir} from "node:os";
import {join} from "node:path";
import test from "node:test";
const installer = new URL("../automation/install-runtime.mjs", import.meta.url).pathname;
function fixture(duplicates = false) {
  const directory = mkdtempSync(join(tmpdir(), "bb-install-test-"));
  const source = join(directory, "source");
  const state = join(directory, "state");
  const bin = join(directory, "bin");
  for (const p of [join(source,"tools"), join(source,".bb/automation/prompts"), state, bin]) mkdirSync(p,{recursive:true});
  writeFileSync(join(source,"tools/bb_perf_dispatch.py"),"# frozen controller\n");
  writeFileSync(join(source,".bb/automation/prompts/DAILY.md"),"daily\n");
  writeFileSync(join(state,"config.json"),'"old-config"\n');
  writeFileSync(join(state,"controller.sh"),'old-script\n');
  writeFileSync(join(bin,"git"),`#!${process.execPath}\nconst args=process.argv.slice(2); console.log(args.includes('--show-toplevel') ? ${JSON.stringify(source)} : args.includes('HEAD') ? 'a'.repeat(40) : '');\n`,{mode:0o700});
  writeFileSync(join(bin,"bb"),`#!${process.execPath}
const fs=require('node:fs'); const args=process.argv.slice(2);
fs.appendFileSync(${JSON.stringify(join(directory,"calls"))},args[1]+'\\n');
if(args[1]==='list') console.log(JSON.stringify(Array.from({length:${duplicates?2:1}},(_,i)=>({id:'auto'+i,name:'DIWire: daily perf PRs and weekly patch releases'}))));
else if(args[1]==='pause') {if(fs.readFileSync(${JSON.stringify(join(state,"config.json"))},'utf8').trim()!=='"old-config"') throw Error('config changed before pause'); console.log('{}');}
else {if(fs.readFileSync(${JSON.stringify(join(state,"config.json"))},'utf8').trim()==='"old-config"') throw Error('new config missing'); console.log('{"id":"auto0"}');}
`,{mode:0o700});
  const args=[installer,'--project','proj_hypmgayr8j','--checkout',source,'--state-root',state,'--provider','codex','--model','gpt-6.1-sol','--reasoning','high'];
  return {directory,state,run:()=>execFileSync(process.execPath,args,{env:{...process.env,PATH:bin+':'+process.env.PATH},encoding:'utf8',stdio:['ignore','pipe','pipe']})};
}
test("upgrade pauses old schedule before changing its config",()=>{
  const f=fixture();try {
    const result=JSON.parse(f.run());
    assert.deepEqual(readFileSync(join(f.directory,'calls'),'utf8').trim().split('\n'),['list','pause','update']);
    assert.equal(result.revision,'a'.repeat(40));
    assert.equal(JSON.parse(readFileSync(join(f.state,'config.json'),'utf8')).release_day,'Monday');
    execFileSync('bash',['-n',join(f.state,'controller.sh')]);
  } finally {rmSync(f.directory,{recursive:true,force:true});}
});
test("duplicate schedules stop installation before shared config changes",()=>{
  const f=fixture(true);try {
    assert.throws(f.run);
    assert.equal(readFileSync(join(f.state,'config.json'),'utf8').trim(),'"old-config"');
    assert.equal(existsSync(join(f.state,'runtime')),false);
  } finally {rmSync(f.directory,{recursive:true,force:true});}
});
