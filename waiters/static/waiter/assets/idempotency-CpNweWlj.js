import{c as s,d as y,o as f,a as b,b as r,f as c,u,t as p,A as g}from"./index-CV_I_GKf.js";/**
 * @license lucide-vue-next v0.468.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const V=s("ArrowLeftIcon",[["path",{d:"m12 19-7-7 7-7",key:"1l729n"}],["path",{d:"M19 12H5",key:"x3x0zl"}]]);/**
 * @license lucide-vue-next v0.468.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const h=s("MinusIcon",[["path",{d:"M5 12h14",key:"1ays0h"}]]);/**
 * @license lucide-vue-next v0.468.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const S=s("PlusIcon",[["path",{d:"M5 12h14",key:"1ays0h"}],["path",{d:"M12 5v14",key:"s699le"}]]),A=["aria-label"],k=["disabled","aria-label"],I=["aria-label"],M=["disabled","aria-label"],N=y({__name:"QuantityStepper",props:{modelValue:{},min:{default:0},max:{default:999},disabled:{type:Boolean,default:!1},label:{default:"Quantity"}},emits:["update:modelValue"],setup(e,{emit:n}){const t=e,i=n;function a(d){i("update:modelValue",Math.max(t.min,Math.min(t.max,t.modelValue+d)))}return(d,o)=>(f(),b("div",{class:"stepper","aria-label":e.label},[r("button",{type:"button",disabled:e.disabled||e.modelValue<=e.min,"aria-label":`Decrease ${e.label}`,onClick:o[0]||(o[0]=m=>a(-1))},[c(u(h),{size:17,"aria-hidden":"true"})],8,k),r("output",{"aria-label":e.label},p(e.modelValue),9,I),r("button",{type:"button",disabled:e.disabled||e.modelValue>=e.max,"aria-label":`Increase ${e.label}`,onClick:o[1]||(o[1]=m=>a(1))},[c(u(S),{size:17,"aria-hidden":"true"})],8,M)],8,A))}});function l(e){return Array.isArray(e)?`[${e.map(l).join(",")}]`:e&&typeof e=="object"?`{${Object.entries(e).sort(([n],[t])=>n.localeCompare(t)).map(([n,t])=>`${JSON.stringify(n)}:${l(t)}`).join(",")}}`:JSON.stringify(e)}async function $(e){const n=new TextEncoder().encode(l(e)),t=await crypto.subtle.digest("SHA-256",n);return Array.from(new Uint8Array(t),i=>i.toString(16).padStart(2,"0")).join("")}function w(){return crypto.randomUUID?.()||`${Date.now()}-${Math.random().toString(16).slice(2)}`}async function D(e,n){const t=`alpha-waiter:command:${e}`,i=await $(n);let a=null;try{a=JSON.parse(localStorage.getItem(t)||"null")}catch{localStorage.removeItem(t)}return(!a||a.fingerprint!==i||Date.now()-a.createdAt>864e5)&&(a={key:w(),fingerprint:i,createdAt:Date.now()},localStorage.setItem(t,JSON.stringify(a))),{key:a.key,clear:()=>localStorage.removeItem(t)}}function O(e){return e instanceof g?e.status>=500||e.status===0||e.code==="COMMAND_IN_PROGRESS":!0}export{V as A,S as P,N as _,D as c,O as s};
