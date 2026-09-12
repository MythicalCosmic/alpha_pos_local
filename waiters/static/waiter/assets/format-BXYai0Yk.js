import{c as i}from"./index-CV_I_GKf.js";/**
 * @license lucide-vue-next v0.468.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const u=i("CheckIcon",[["path",{d:"M20 6 9 17l-5-5",key:"1gmf2c"}]]);/**
 * @license lucide-vue-next v0.468.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const m=i("Clock3Icon",[["circle",{cx:"12",cy:"12",r:"10",key:"1mglay"}],["polyline",{points:"12 6 12 12 16.5 12",key:"1aq6pp"}]]),n={uz:"uz-UZ",en:"en-GB",ru:"ru-RU"};function c(t,r="uz"){const e=Number(t??0);return Number.isFinite(e)?new Intl.NumberFormat(n[r],{maximumFractionDigits:0}).format(e):"0"}function s(t,r="uz"){if(!t)return"—";const e=new Date(t);return Number.isNaN(e.getTime())?"—":new Intl.DateTimeFormat(n[r],{hour:"2-digit",minute:"2-digit"}).format(e)}function f(t,r="uz"){if(!t)return"—";const e=new Date(t);return Number.isNaN(e.getTime())?"—":new Intl.DateTimeFormat(n[r],{day:"2-digit",month:"short",hour:"2-digit",minute:"2-digit"}).format(e)}function E(t){if(!t)return 0;const r=new Date(t);return Number.isNaN(r.getTime())?0:Math.max(0,Math.floor((Date.now()-r.getTime())/6e4))}function o(t){return t==="CANCELLED"?"CANCELED":t}function d(t,r=!1){if(r||t==="COMPLETED")return"settled";const e=o(t);return e==="READY"||e==="AVAILABLE"?"ready":e==="PREPARING"||e==="OCCUPIED"||e==="OPEN"?"working":e==="RESERVED"?"waiting":e==="CANCELED"||e==="OUT_OF_SERVICE"?"danger":"neutral"}export{m as C,f as a,u as b,d as c,E as e,c as m,o as n,s};
