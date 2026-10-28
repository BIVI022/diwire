import assert from "node:assert/strict";
import {execFileSync} from "node:child_process";
import {mkdtempSync, mkdirSync, readFileSync, writeFileSync, rmSync, existsSync} from "node:fs";
import {tmpdir} from "node:os";
import {join} from "node:path";
import test from "node:test";
const installer = new URL("../automation/install-runtime.mjs", import.meta.url).pathname;
function fixture({matches = 1, checkoutMode = "source", sourceHead = "a"} = {}) {
  const directory = mkdtempSync(join(tmpdir(), "bb-install-test-"));
  const source = join(directory, "source");
  const alternate = join(directory, "alternate");
  const foreign = join(directory, "foreign");
  const state = join(directory, "state");
  const bin = join(directory, "bin");
  const common = join(source, ".git");
  const foreignCommon = join(foreign, ".git");
  for (const p of [join(source,"tools"),join(source,".bb/automation/prompts"),state,bin,common,alternate,foreignCommon]) mkdirSync(p,{recursive:true});
  writeFileSync(join(source,"tools/bb_perf_dispatch.py"),"# frozen controller\n");
  writeFileSync(join(source,".bb/automation/prompts/DAILY.md"),"daily\n");
  writeFileSync(join(source,".bb/automation/merge-gate.mjs"),"// frozen gate\n");
  writeFileSync(join(state,"config.json"),'"old-config"\n');
  writeFileSync(join(state,"controller.sh"),'old-script\n');
  writeFileSync(join(bin,"git"),`#!${process.execPath}
const args=process.argv.slice(2); const ci=args.indexOf('-C'); const dir=ci<0?${JSON.stringify(source)}:args[ci+1];
if(args.includes('--show-toplevel')) console.log(dir);
else if(args.includes('--git-common-dir')) console.log(dir===${JSON.stringify(foreign)}?${JSON.stringify(foreignCommon)}:${JSON.stringify(common)});
else if(args.includes('HEAD')) console.log((dir===${JSON.stringify(alternate)}?'b':${JSON.stringify(sourceHead)}).repeat(40));
else if(args.includes('origin/main')) console.log('a'.repeat(40));
else console.log('');
`,{mode:0o700});
  writeFileSync(join(bin,"bb"),`#!${process.execPath}
const fs=require('node:fs'); const args=process.argv.slice(2);
fs.appendFileSync(${JSON.stringify(join(directory,"calls"))},JSON.stringify(args)+'\\n');
if(args[1]==='list') console.log(JSON.stringify(Array.from({length:${matches}},(_,i)=>({id:'auto'+i,name:'DIWire: daily perf PRs and weekly patch releases'}))));
else if(args[1]==='pause') {if(fs.readFileSync(${JSON.stringify(join(state,"config.json"))},'utf8').trim()!=='"old-config"') throw Error('config changed before pause'); console.log('{}');}
else {if(fs.readFileSync(${JSON.stringify(join(state,"config.json"))},'utf8').trim()==='"old-config"') throw Error('new config missing'); console.log('{"id":"auto0"}');}
`,{mode:0o700});
  const checkout={source,alternate,foreign,missing:join(directory,"missing")}[checkoutMode];
  const args=[installer,'--project','proj_hypmgayr8j','--checkout',checkout,'--state-root',state,'--provider','codex','--model','gpt-6.1-sol','--reasoning','high'];
  const calls=()=>readFileSync(join(directory,'calls'),'utf8').trim().split('\n').map(JSON.parse);
  return {directory,state,checkout,calls,run:()=>execFileSync(process.execPath,args,{env:{...process.env,PATH:bin+':'+process.env.PATH},encoding:'utf8',stdio:['ignore','pipe','pipe']})};
}
test("upgrade pauses old schedule before changing its config",()=>{
  const f=fixture();try {
    const result=JSON.parse(f.run());
    assert.deepEqual(f.calls().map(a=>a[1]),['list','pause','update']);
    assert.ok(!f.calls().at(-1).some(a=>a==='--enabled'||a==='--enable'));
    assert.equal(result.revision,'a'.repeat(40));
    assert.equal(JSON.parse(readFileSync(join(f.state,'config.json'),'utf8')).release_day,'Monday');
    execFileSync('bash',['-n',join(f.state,'controller.sh')]);
  } finally {rmSync(f.directory,{recursive:true,force:true});}
});
test("duplicate schedules stop installation before shared config changes",()=>{
  const f=fixture({matches:2});try {
    assert.throws(f.run);
    assert.equal(readFileSync(join(f.state,'config.json'),'utf8').trim(),'"old-config"');
    assert.equal(existsSync(join(f.state,'runtime')),false);
  } finally {rmSync(f.directory,{recursive:true,force:true});}
});
test("a first installation creates a paused automation",()=>{
  const f=fixture({matches:0});try {
    f.run();
    assert.deepEqual(f.calls().map(a=>a[1]),['list','create']);
    assert.ok(f.calls()[1].includes('--disabled'));
  } finally {rmSync(f.directory,{recursive:true,force:true});}
});
for(const checkoutMode of ['missing','foreign']) test(`${checkoutMode} checkout is rejected before any schedule change`,()=>{
  const f=fixture({checkoutMode});try {
    assert.throws(f.run);
    assert.equal(existsSync(join(f.directory,'calls')),false);
    assert.equal(readFileSync(join(f.state,'config.json'),'utf8').trim(),'"old-config"');
  } finally {rmSync(f.directory,{recursive:true,force:true});}
});
test("a coordinator checkout can share the reviewed repository with a different head",()=>{
  const f=fixture({checkoutMode:'alternate'});try {
    const result=JSON.parse(f.run());
    assert.equal(result.revision,'a'.repeat(40));
    assert.equal(JSON.parse(readFileSync(join(f.state,'config.json'),'utf8')).checkout,f.checkout);
  } finally {rmSync(f.directory,{recursive:true,force:true});}
});

test("candidate acceptance code cannot be installed before merge",()=>{
  const f=fixture({sourceHead:"b"});try {
    assert.throws(f.run);
    assert.equal(existsSync(join(f.directory,'calls')),false);
    assert.equal(readFileSync(join(f.state,'config.json'),'utf8').trim(),'"old-config"');
  } finally {rmSync(f.directory,{recursive:true,force:true});}
});
