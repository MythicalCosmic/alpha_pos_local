import{c as l,b as e,C as i}from"./format-BXYai0Yk.js";import{c as o,d as p,a as d,x as m,k as f,M as E,b as C,t as y,u as k,h as D,D as s,o as c,X as h}from"./index-CV_I_GKf.js";import{L}from"./lock-keyhole-Dx7av93v.js";/**
 * @license lucide-vue-next v0.468.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const R=o("CircleDotIcon",[["circle",{cx:"12",cy:"12",r:"10",key:"1mglay"}],["circle",{cx:"12",cy:"12",r:"1",key:"41hilf"}]]);/**
 * @license lucide-vue-next v0.468.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const x=o("ReceiptTextIcon",[["path",{d:"M4 2v20l2-1 2 1 2-1 2 1 2-1 2 1 2-1 2 1V2l-2 1-2-1-2 1-2-1-2 1-2-1-2 1Z",key:"q3az6g"}],["path",{d:"M14 8H8",key:"1l3xfs"}],["path",{d:"M16 12H8",key:"1fr5h0"}],["path",{d:"M13 16H8",key:"wsln4y"}]]),P=p({__name:"StatusBadge",props:{status:{},paid:{type:Boolean,default:!1},compact:{type:Boolean,default:!1}},setup(a){const t=a,n=s(()=>t.paid?"PAID":t.status),r=s(()=>l(t.status,t.paid)),u=s(()=>t.paid||t.status==="COMPLETED"?e:t.status==="READY"||t.status==="AVAILABLE"?e:t.status==="PREPARING"||t.status==="OCCUPIED"||t.status==="OPEN"?R:t.status==="RESERVED"?i:t.status==="OUT_OF_SERVICE"?L:t.status==="CANCELED"||t.status==="CANCELLED"?h:x);return(A,B)=>(c(),d("span",{class:m(["status-badge",[`status-badge--${r.value}`,{compact:a.compact}]])},[(c(),f(E(u.value),{size:a.compact?13:14,"aria-hidden":"true"},null,8,["size"])),C("span",null,y(k(D)(`status.${n.value}`)),1)],2))}});export{x as R,P as _};
