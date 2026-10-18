import assert from "node:assert/strict";
import { Panel } from "./harness.mjs";

// Eine kontrollierte Uhr prueft Dienstaufrufe, nicht nur angelegte Timer.
// Auch Promise-Fortsetzungen duerfen erst laufen, bevor die Zeit weitergeht.
async function withClock(test){
  let now=0, nextId=0;
  const timers=new Map();
  const saved=Object.fromEntries(["performance","setTimeout","clearTimeout"].map(
    key=>[key,Object.getOwnPropertyDescriptor(globalThis,key)]));
  const flush=async()=>{for(let i=0;i<30;i++)await Promise.resolve();};
  const clock={
    now:()=>now,
    timerCount:()=>timers.size,
    waits:[],
    later(ms,fn){return setTimeout(fn,ms);},
    async run(promise){
      let done=false, error;
      Promise.resolve(promise).then(()=>{done=true;},e=>{error=e;done=true;});
      for(let step=0;step<1000;step++){
        await flush();
        if(done){if(error)throw error;return;}
        assert.ok(timers.size,"Promise wartet ohne Timer");
        const [id,timer]=[...timers].sort((a,b)=>a[1].at-b[1].at||a[0]-b[0])[0];
        timers.delete(id);
        now=timer.at;
        timer.fn();
      }
      assert.fail("Zeitplanung endet nicht");
    },
  };
  Object.defineProperty(globalThis,"performance",{configurable:true,value:{now:()=>now}});
  globalThis.setTimeout=(fn,ms)=>{
    assert.ok(Number.isFinite(ms)&&ms>=0,"ungueltige Wartezeit");
    clock.waits.push(ms);
    const id=++nextId;
    timers.set(id,{at:now+ms,fn});
    return id;
  };
  globalThis.clearTimeout=id=>timers.delete(id);
  try{await test(clock);}
  finally{
    for(const [key,descriptor] of Object.entries(saved)){
      if(descriptor)Object.defineProperty(globalThis,key,descriptor);
      else delete globalThis[key];
    }
  }
}

const area=(id,delay)=>({id,name:id,mode:"none",drive_delay:delay});
const shutter=(id,up="a",down=up)=>({
  cover_entity_id:`cover.${id}`,name:id,area_up_id:up,area_down_id:down,
  position_closed:10,position_sun_protect:40,position_when_window_tilted:60,
});
function panel(clock,areas,shutters,gap=0){
  const p=Object.create(Panel.prototype), log=[];
  p.t=k=>k;
  p.requestUpdate=()=>{};
  p._data={areas,shutters,settings:{min_drive_gap:gap},auto_modes:{}};
  p.hass={
    states:{},user:{is_admin:false},language:"de",
    callService:async(domain,service,data)=>{
      log.push({at:clock.now(),domain,service,...data});
    },
    callWS:async()=>assert.fail("Fahrten muessen cover-Dienste direkt aufrufen"),
  };
  return {p,log};
}
const times=log=>log.map(c=>c.at);
const drives=log=>log.map(c=>[c.entity_id,c.at]);

// Die echten Klick-Handler aus Lit-Templates auslesen: so faellt auch eine
// vergessene Bereichs-ID am Knopf auf, nicht nur ein Fehler im Scheduler.
function click(template,classes){
  if(Array.isArray(template)){
    for(const value of template){const found=click(value,classes);if(found)return found;}
  }else if(template?._s){
    for(let i=0;i<template._v.length;i++){
      const value=template._v[i];
      if(typeof value==="function"&&/@click=$/.test(template._s[i])){
        const prefix=template._s.slice(0,i+1).join("");
        const button=prefix.slice(prefix.lastIndexOf("<button"));
        if(button.includes(`class="${classes}"`))return value;
      }
      const found=click(value,classes);
      if(found)return found;
    }
  }
  return null;
}
function button(p,scope,action){
  const template=scope?p._dashCard(scope,p._data):p._renderGlobalCard(p._data);
  const handler=click(template,`btn ${action}`);
  assert.equal(typeof handler,"function",`Knopf fehlt: ${action}`);
  return handler();
}
function rowStop(p,s){
  const handler=click(p._rowButtons(s),"rbtn stop");
  assert.equal(typeof handler,"function","Einzel-Stopp fehlt");
  return handler();
}
function assertIdle(p,clock){
  assert.equal(p._coverPlans?.size??0,0,"Gruppenfahrt bleibt registriert");
  assert.equal(clock.timerCount(),0,"Zeitgeber bleibt nach Abschluss aktiv");
}

let passed=0, failed=0;
async function test(name,fn){
  try{await withClock(fn);passed++;console.log("  ok   "+name);}
  catch(e){failed++;console.error("  FAIL "+name+"\n"+e.stack);}
}

for(const action of ["open","close","sun","vent"]){
  await test(`Bereichsknopf ${action}: angeklickter Bereich, nicht Richtungsbereich`,async clock=>{
    const selected=area("a",5);
    const {p,log}=panel(clock,[selected,area("b",17)],[
      shutter("one","a","b"),shutter("two","a","b"),shutter("other","b"),
    ]);
    await clock.run(button(p,selected,action));
    assert.deepEqual(drives(log),[["cover.one",0],["cover.two",5000]]);
    assert.ok(log.every(c=>c.domain==="cover"));
    assert.ok(log.every(c=>c.service===({
      open:"open_cover",close:"close_cover",sun:"set_cover_position",vent:"set_cover_position",
    })[action]));
    if(action==="sun"||action==="vent")
      assert.ok(log.every(c=>c.position===(action==="sun"?40:60)));
  });

  await test(`Globaler Knopf ${action}: Hoch-/Runter-Zuordnung und getrennte Fristen`,async clock=>{
    const {p,log}=panel(clock,[area("fast",5),area("slow",12)],[
      shutter("a1","fast","slow"),shutter("a2","fast","slow"),
      shutter("b1","slow","fast"),shutter("b2","slow","fast"),
    ]);
    await clock.run(button(p,null,action));
    const open=action==="open";
    assert.deepEqual(drives(log),[
      ["cover.a1",0],["cover.b1",0],
      [open?"cover.a2":"cover.b2",5000],[open?"cover.b2":"cover.a2",12000],
    ]);
  });
}

for(const [delay,gap,expected] of [
  [0,0,[0,0,0]],[5,0,[0,5000,10000]],[5,10,[0,10000,20000]],
  [10,5,[0,10000,20000]],[120,0,[0,120000,240000]],
]){
  await test(`Bereich ${delay}s / global ${gap}s: keine Addition`,async clock=>{
    const {p,log}=panel(clock,[area("a",delay)],[
      shutter("one"),shutter("two"),shutter("three"),
    ],gap);
    await clock.run(p._coverAction(p._data.shutters,"close",true,"a"));
    assert.deepEqual(times(log),expected);
    if(!delay&&!gap)assert.deepEqual(clock.waits,[]);
  });
}

for(const [value,expected] of [
  [undefined,10],[null,10],["",10],["nass",10],[Infinity,10],[[],10],
  ["5",5],["5.5",10],[5.9,5],[-5,0],
]){
  await test(`Bereichswert ${value===Infinity?"Infinity":JSON.stringify(value)}: ${expected}s`,async clock=>{
    const {p,log}=panel(clock,[area("a",value)],[shutter("one"),shutter("two")]);
    await clock.run(p._coverAction(p._data.shutters,"close",true,"a"));
    assert.deepEqual(times(log),[0,expected*1000]);
  });
}

await test("Fehlende Bereichszuordnung bildet keinen kuenstlichen Bereich",async clock=>{
  const {p,log}=panel(clock,[area("a",30)],[
    shutter("one","",""),shutter("two","deleted","deleted"),
  ],2);
  await clock.run(button(p,null,"close"));
  assert.deepEqual(times(log),[0,2000]);
});

await test("Globale Fahrt nutzt freie Bereiche und haelt die Bereichsreihenfolge",async clock=>{
  const {p,log}=panel(clock,[area("a",10),area("b",3)],[
    shutter("a1"),shutter("a2"),shutter("a3"),shutter("b1","b"),shutter("b2","b"),
  ],2);
  await clock.run(button(p,null,"close"));
  assert.deepEqual(drives(log),[
    ["cover.a1",0],["cover.b1",2000],["cover.b2",5000],
    ["cover.a2",10000],["cover.a3",20000],
  ]);
});

await test("Doppelte Cover werden nur einmal angesteuert",async clock=>{
  const one=shutter("one"), two=shutter("two");
  const {p,log}=panel(clock,[area("a",5)],[one,{...one},two]);
  await clock.run(button(p,null,"close"));
  assert.deepEqual(drives(log),[["cover.one",0],["cover.two",5000]]);
});

await test("Dienstlaufzeit wird angerechnet, nicht zur Frist addiert",async clock=>{
  const {p,log}=panel(clock,[area("a",5)],[shutter("one"),shutter("two")],10);
  const call=p.hass.callService;
  p.hass.callService=async(...args)=>{
    await call(...args);
    await new Promise(resolve=>setTimeout(resolve,3000));
  };
  await clock.run(button(p,null,"close"));
  assert.deepEqual(times(log),[0,10000]);
});

await test("Stopp hat nur den bisherigen globalen Abstand",async clock=>{
  const {p,log}=panel(clock,[area("a",120)],[
    shutter("one"),shutter("two"),shutter("three"),
  ],2);
  await clock.run(button(p,null,"stop"));
  assert.deepEqual(times(log),[0,2000,4000]);
  assert.ok(log.every(c=>c.service==="stop_cover"));
});

await test("Stopp wartet nicht hinter einer laufenden Gruppenfahrt",async clock=>{
  const {p,log}=panel(clock,[area("a",120)],[shutter("one"),shutter("two")],2);
  const closing=button(p,null,"close");
  let stopping;
  clock.later(1000,()=>{stopping=button(p,null,"stop");});
  await clock.run(closing);
  assert.equal(clock.now(),1000,"Abbruch darf nicht die alte Bereichsfrist abwarten");
  await clock.run(stopping);
  assert.deepEqual(drives(log.filter(c=>c.service==="stop_cover")),[
    ["cover.one",1000],["cover.two",3000],
  ]);
  assert.deepEqual(times(log.filter(c=>c.service==="close_cover")),[0]);
  assertIdle(p,clock);
});

await test("Globales Stopp verwirft mehrere gleichzeitig laufende Gruppenfahrten",async clock=>{
  const a=area("a",5), b=area("b",10);
  const {p,log}=panel(clock,[a,b],[
    shutter("a1"),shutter("a2"),shutter("b1","b"),shutter("b2","b"),
  ],2);
  const moving=Promise.all([button(p,a,"sun"),button(p,b,"vent")]);
  let stopping;
  clock.later(1000,()=>{stopping=button(p,null,"stop");});
  await clock.run(moving);
  assert.equal(clock.now(),1000);
  await clock.run(stopping);
  assert.deepEqual(drives(log.filter(c=>c.service!=="stop_cover")),[
    ["cover.a1",0],["cover.b1",0],
  ]);
  assert.deepEqual(times(log.filter(c=>c.service==="stop_cover")),[1000,3000,5000,7000]);
  assertIdle(p,clock);
});

await test("Bereichs-Stopp entfernt seine Ziele auch aus globalen und anderen Fahrten",async clock=>{
  const a=area("a",5), b=area("b",10);
  const {p,log}=panel(clock,[a,b],[
    shutter("a1"),shutter("a2"),shutter("b1","b"),shutter("b2","b"),
  ]);
  const moving=Promise.all([button(p,null,"close"),button(p,a,"open")]);
  let stopping;
  clock.later(1000,()=>{stopping=button(p,a,"stop");});
  await clock.run(moving);
  await clock.run(stopping);
  assert.deepEqual(drives(log.filter(c=>c.service==="close_cover")),[
    ["cover.a1",0],["cover.b1",0],["cover.b2",10000],
  ]);
  assert.deepEqual(drives(log.filter(c=>c.service==="open_cover")),[["cover.a1",0]]);
  assert.deepEqual(drives(log.filter(c=>c.service==="stop_cover")),[
    ["cover.a1",1000],["cover.a2",1000],
  ]);
  assertIdle(p,clock);
});

await test("Einzel-Stopp entfernt nur das noch nicht gestartete Geraet",async clock=>{
  const {p,log}=panel(clock,[area("a",5)],[
    shutter("one"),shutter("two"),shutter("three"),
  ]);
  const moving=button(p,null,"close");
  let stopping;
  clock.later(1000,()=>{stopping=rowStop(p,p._data.shutters[1]);});
  await clock.run(moving);
  await clock.run(stopping);
  assert.deepEqual(drives(log.filter(c=>c.service==="close_cover")),[
    ["cover.one",0],["cover.three",5000],
  ]);
  assert.deepEqual(drives(log.filter(c=>c.service==="stop_cover")),[["cover.two",1000]]);
  assertIdle(p,clock);
});

await test("Abbruch loest auch eine globale Wartezeit sofort auf",async clock=>{
  const {p,log}=panel(clock,[area("a",0)],[shutter("one"),shutter("two")],10);
  const moving=button(p,null,"close");
  let stopping;
  clock.later(1000,()=>{stopping=rowStop(p,p._data.shutters[1]);});
  await clock.run(moving);
  assert.equal(clock.now(),1000);
  await clock.run(stopping);
  assert.deepEqual(times(log.filter(c=>c.service==="close_cover")),[0]);
  assertIdle(p,clock);
});

await test("Stopp waehrend eines laufenden Dienstaufrufs verhindert dessen Folgebefehle",async clock=>{
  const {p,log}=panel(clock,[area("a",5)],[shutter("one"),shutter("two")]);
  const call=p.hass.callService;
  p.hass.callService=async(...args)=>{
    await call(...args);
    if(args[1]!=="stop_cover")await new Promise(resolve=>setTimeout(resolve,3000));
  };
  const moving=button(p,null,"close");
  let stopping;
  clock.later(1000,()=>{stopping=button(p,null,"stop");});
  await clock.run(moving);
  await clock.run(stopping);
  assert.deepEqual(times(log.filter(c=>c.service==="close_cover")),[0]);
  assert.deepEqual(times(log.filter(c=>c.service==="stop_cover")),[1000,1000]);
  assertIdle(p,clock);
});

await test("Wiederholtes Stopp reaktiviert nichts und ein neuer Fahrklick bleibt moeglich",async clock=>{
  const {p,log}=panel(clock,[area("a",5)],[shutter("one"),shutter("two")]);
  const moving=button(p,null,"close");
  let stopping, stoppingAgain;
  clock.later(1000,()=>{stopping=button(p,null,"stop");});
  clock.later(1500,()=>{stoppingAgain=button(p,null,"stop");});
  const restarting=new Promise(resolve=>clock.later(2000,()=>resolve(button(p,null,"close"))));
  await clock.run(Promise.all([moving,restarting]));
  await clock.run(Promise.all([stopping,stoppingAgain]));
  assert.deepEqual(drives(log.filter(c=>c.service==="close_cover")),[
    ["cover.one",0],["cover.one",2000],["cover.two",7000],
  ]);
  assertIdle(p,clock);
});

await test("Schon vorgemerkte Stoppbefehle werden nicht durch ein weiteres Stopp geloescht",async clock=>{
  const {p,log}=panel(clock,[area("a",120)],[shutter("one"),shutter("two")],2);
  const moving=button(p,null,"close");
  let stopping, singleStop;
  clock.later(1000,()=>{stopping=button(p,null,"stop");});
  clock.later(1500,()=>{singleStop=rowStop(p,p._data.shutters[0]);});
  const finished=new Promise(resolve=>clock.later(4000,resolve));
  await clock.run(Promise.all([moving,finished]));
  await clock.run(Promise.all([stopping,singleStop]));
  assert.deepEqual(drives(log.filter(c=>c.service==="stop_cover")),[
    ["cover.one",1000],["cover.one",1500],["cover.two",3000],
  ]);
  assert.deepEqual(times(log.filter(c=>c.service==="close_cover")),[0]);
  assertIdle(p,clock);
});

await test("Automatikschalter verhindern weder Abbruch noch Stopp",async clock=>{
  const {p,log}=panel(clock,[area("a",5)],[
    {...shutter("one"),shutter_auto_entity_id:"switch.one"},
    shutter("two"),{...shutter("off"),automation_enabled:false,shading_enabled:false},
  ]);
  p.hass.states["switch.one"]={state:"on"};
  const moving=button(p,null,"close");
  let stopping;
  clock.later(1000,()=>{
    p.hass.states["switch.one"]={state:"off"};
    stopping=button(p,null,"stop");
  });
  await clock.run(moving);
  await clock.run(stopping);
  assert.deepEqual(drives(log.filter(c=>c.service==="stop_cover")),[
    ["cover.one",1000],["cover.two",1000],["cover.off",1000],
  ]);
  assert.deepEqual(times(log.filter(c=>c.service==="close_cover")),[0]);
  assertIdle(p,clock);
});

await test("Fehlgeschlagener Stopp reaktiviert keine verworfenen Bewegungen",async clock=>{
  const {p,log}=panel(clock,[area("a",5)],[shutter("one"),shutter("two")]);
  const call=p.hass.callService;
  p.hass.callService=async(...args)=>{
    await call(...args);
    if(args[1]==="stop_cover")throw new Error("Stopp-Testfehler");
  };
  const moving=button(p,null,"close");
  let stopping;
  clock.later(1000,()=>{
    stopping=assert.rejects(button(p,null,"stop"),/Stopp-Testfehler/);
  });
  await clock.run(moving);
  await clock.run(stopping);
  assert.deepEqual(times(log.filter(c=>c.service==="close_cover")),[0]);
  assertIdle(p,clock);
});

await test("Fehlgeschlagene Gruppenfahrt hinterlaesst weder Registereintrag noch Timer",async clock=>{
  const {p}=panel(clock,[area("a",5)],[shutter("one"),shutter("two")]);
  p.hass.callService=async()=>{throw new Error("Fahrt-Testfehler");};
  await clock.run(assert.rejects(button(p,null,"close"),/Fahrt-Testfehler/));
  assertIdle(p,clock);
});

await test("Stopp greift nicht in andere Panel-Instanzen ein",async clock=>{
  const areas=[area("a",5)], shutters=[shutter("one"),shutter("two")];
  const first=panel(clock,areas,shutters), second=panel(clock,areas,shutters);
  const moving=Promise.all([button(first.p,null,"close"),button(second.p,null,"close")]);
  let stopping;
  clock.later(1000,()=>{stopping=button(first.p,null,"stop");});
  await clock.run(moving);
  await clock.run(stopping);
  assert.deepEqual(times(first.log.filter(c=>c.service==="close_cover")),[0]);
  assert.deepEqual(times(second.log.filter(c=>c.service==="close_cover")),[0,5000]);
  assertIdle(first.p,clock);
  assertIdle(second.p,clock);
});

await test("Ohne Wartezeit bereits gesendete Befehle lassen sich nicht zurueckholen",async clock=>{
  const {p,log}=panel(clock,[area("a",0)],[shutter("one"),shutter("two")]);
  const moving=button(p,null,"close");
  const stopping=new Promise(resolve=>clock.later(1000,()=>resolve(button(p,null,"stop"))));
  await clock.run(Promise.all([moving,stopping]));
  assert.deepEqual(times(log.filter(c=>c.service==="close_cover")),[0,0]);
  assert.deepEqual(times(log.filter(c=>c.service==="stop_cover")),[1000,1000]);
  assertIdle(p,clock);
});

await test("Bereits ausgewaehlter Stopp bleibt trotz Automatikwechsel erhalten",async clock=>{
  const {p,log}=panel(clock,[area("a",120)],[shutter("one"),shutter("two")],2);
  p._data.shutters[1].shutter_auto_entity_id="switch.two";
  p.hass.states["switch.two"]={state:"on"};
  clock.later(1000,()=>{p.hass.states["switch.two"]={state:"off"};});
  await clock.run(button(p,null,"stop"));
  assert.deepEqual(drives(log),[["cover.one",0],["cover.two",2000]]);
});

await test("Einzelknopf ignoriert Bereichswartezeit und Automatikschalter",async clock=>{
  const s={...shutter("one"),automation_enabled:false};
  const {p,log}=panel(clock,[area("a",120)],[s]);
  const handler=click(p._rowButtons(s),"rbtn down");
  assert.equal(typeof handler,"function");
  await clock.run(handler());
  assert.deepEqual(times(log),[0]);
});

await test("Zwei gleichzeitig gestartete Gruppenfahrten bleiben unabhaengig",async clock=>{
  const {p,log}=panel(clock,[area("a",5),area("b",5)],[
    shutter("a1"),shutter("a2"),shutter("b1","b"),shutter("b2","b"),
  ],2);
  await clock.run(Promise.all([
    p._coverAction(p._data.shutters.slice(0,2),"close",true,"a"),
    p._coverAction(p._data.shutters.slice(2),"close",true,"b"),
  ]));
  assert.deepEqual(drives(log),[
    ["cover.a1",0],["cover.b1",0],["cover.a2",5000],["cover.b2",5000],
  ]);
});

await test("Ausgeschaltete Automatik wird vor und nach dem Warten beachtet",async clock=>{
  const off={...shutter("off"),automation_enabled:false};
  const {p,log}=panel(clock,[area("a",5)],[off,shutter("one"),shutter("two"),shutter("three")]);
  p._data.shutters[2].shutter_auto_entity_id="switch.two";
  p.hass.states["switch.two"]={state:"on"};
  clock.later(1000,()=>{p.hass.states["switch.two"]={state:"off"};});
  await clock.run(button(p,null,"close"));
  assert.deepEqual(drives(log),[["cover.one",0],["cover.three",5000]]);
});

await test("Beschattungsausstieg wird vor und nach dem Warten beachtet",async clock=>{
  const {p,log}=panel(clock,[area("a",5)],[
    {...shutter("off"),shading_enabled:false},shutter("one"),shutter("two"),shutter("three"),
  ]);
  clock.later(1000,()=>{
    p._data={...p._data,shutters:p._data.shutters.map(s=>
      s.cover_entity_id==="cover.two"?{...s,shading_enabled:false}:s)};
  });
  await clock.run(button(p,null,"sun"));
  assert.deepEqual(drives(log),[["cover.one",0],["cover.three",5000]]);
});

function setGuard(p,cover,on){
  p.hass.states[`binary_sensor.guard_${cover}`]={
    entity_id:`binary_sensor.guard_${cover}`,state:on?"on":"off",
    attributes:{cover_entity_id:`cover.${cover}`,release_in_seconds:on?60:0},
  };
}
for(const kind of ["awning","window"]){
  for(const action of ["open","sun"]){
    await test(`${kind}: Schutz greift auch waehrend ${action}-Wartezeit`,async clock=>{
      const {p,log}=panel(clock,[area("a",5)],[
        shutter("one"),{...shutter("guarded"),device_kind:kind},shutter("three"),
      ]);
      setGuard(p,"guarded",false);
      clock.later(1000,()=>setGuard(p,"guarded",true));
      await clock.run(button(p,null,action));
      assert.deepEqual(drives(log),[["cover.one",0],["cover.three",5000]]);
    });
  }
  await test(`${kind}: Sperre erlaubt Einfahren/Schliessen und Stopp, kein Lueften`,async clock=>{
    const s={...shutter("guarded"),device_kind:kind};
    const {p,log}=panel(clock,[area("a",5)],[s]);
    setGuard(p,"guarded",true);
    for(const action of ["open","sun","vent","close","stop"])
      await clock.run(button(p,null,action));
    assert.deepEqual(log.map(c=>c.service),["close_cover","stop_cover"]);
  });
}

for(const action of ["close","sun","vent"]){
  await test(`Fenster oeffnet waehrend ${action}-Wartezeit: Aussperrschutz bleibt aktiv`,async clock=>{
    const s={...shutter("door"),lock_protection:true,window_entity_id:"binary_sensor.door",
      window_open_state:"on",min_position_when_open:80};
    const {p,log}=panel(clock,[area("a",5)],[shutter("one"),s]);
    p.hass.states["binary_sensor.door"]={state:"off"};
    clock.later(1000,()=>{p.hass.states["binary_sensor.door"]={state:"on"};});
    await clock.run(button(p,null,action));
    assert.equal(log[1].service,"set_cover_position");
    assert.equal(log[1].position,80);
    assert.equal(log[1].at,5000);
  });
}

console.log(`Timing-Tests: ${passed} bestanden, ${failed} fehlgeschlagen`);
process.exitCode=failed?1:0;
