'use strict';
// Explicit scalar/choice rules only. Formula equivalence remains self-assessment.
((root)=>{
 const object=x=>!!x&&typeof x==='object'&&!Array.isArray(x);
 const finite=x=>typeof x==='number'&&Number.isFinite(x)&&(!Number.isInteger(x)||Number.isSafeInteger(x));
 const options=f=>Array.isArray(f.options)?f.options.map((o,i)=>object(o)?o.value:typeof o==='string'?String(i):null):[];
 function validate(q){
  if(!object(q))return ['题目格式无效'];
  const g=q.grading===undefined?{kind:'self'}:q.grading;
  if(!object(g))return ['判分规则格式无效'];
  if(g.kind==='self')return [];
  if(!['numeric','choice'].includes(g.kind))return ['不支持的自动判分类型'];
  const errors=[],fields=new Map(),seen=new Set();
  if(q.answer?.status!=='ready')errors.push('参考答案尚未就绪');
  if(typeof g.rationale!=='string'||!g.rationale.trim())errors.push('缺少判分依据');
  if(!Array.isArray(q.parts))return [...errors,'缺少作答字段'];
  for(const p of q.parts){
   if(!Array.isArray(p?.fields)){errors.push('作答字段格式无效');continue}
   for(const f of p.fields){if(!object(f)||typeof f.id!=='string'||!f.id){errors.push('作答字段身份无效');continue}if(fields.has(f.id))errors.push('重复作答字段');fields.set(f.id,f)}
  }
  if(!Array.isArray(g.rules)||!g.rules.length)return [...errors,'缺少判分规则'];
  for(const r of g.rules){
   if(!object(r)||typeof r.fieldId!=='string'){errors.push('判分规则格式无效');continue}
   if(seen.has(r.fieldId))errors.push('同一字段存在重复规则');seen.add(r.fieldId);
   const f=fields.get(r.fieldId);if(!f){errors.push('判分规则引用了不存在的字段');continue}
   if(g.kind==='numeric'){
    if(!['number','fill'].includes(f.kind))errors.push('数值判分只支持数值或填空字段');
    if(!finite(r.expected))errors.push('参考值必须是有限数字，整数须在安全精度范围内');
    if('tolerance'in r&&(!finite(r.tolerance)||r.tolerance<0))errors.push('容差必须非负、有限，整数须在安全精度范围内');
   }else{
    if(!['choice','multiple'].includes(f.kind)){errors.push('选择题规则与输入类型不符');continue}
    const values=options(f);if(!values.length||values.some(v=>typeof v!=='string'||!v)||new Set(values).size!==values.length){errors.push('选项值必须是唯一字符串');continue}
    if(f.kind==='choice'){if(typeof r.expected!=='string'||!values.includes(r.expected))errors.push('参考选项不存在')}
    else if(!Array.isArray(r.expected)||!r.expected.length||r.expected.some(v=>typeof v!=='string'||!values.includes(v))||new Set(r.expected).size!==r.expected.length)errors.push('参考多选项无效或重复');
   }
  }
  if(!fields.size||fields.size!==seen.size||[...fields.keys()].some(id=>!seen.has(id)))errors.push('自动规则必须覆盖所有作答字段；混合主观内容须自评');
  return [...new Set(errors)];
 }
 function decimal(text){
  const [mantissa,exp='0']=text.toLowerCase().split('e'),negative=mantissa.startsWith('-'),unsigned=mantissa.replace(/^[+-]/,''),point=unsigned.indexOf('.');
  let digits=unsigned.replace('.','').replace(/^0+/,''),power=Number(exp)-(point<0?0:unsigned.length-point-1);
  if(!digits)return {digits:'0',power:0,negative:false};
  const tail=digits.length-digits.replace(/0+$/,'').length;digits=digits.slice(0,digits.length-tail);power+=tail;
  return {digits,power,negative};
 }
 const decimalKey=p=>(p.negative?'-':'')+p.digits+'e'+p.power;
 function withinTolerance(value,expected,tolerance){
  const parts=[value,expected,tolerance].map(v=>decimal(String(v))),power=Math.min(...parts.map(p=>p.power));
  const integers=parts.map(p=>(p.negative?-1n:1n)*BigInt(p.digits)*10n**BigInt(p.power-power)),difference=integers[0]-integers[1];
  return (difference<0n?-difference:difference)<=integers[2];
 }
 function parseNumeric(input){
  if(typeof input!=='string')return {ok:false,message:'请填写数字；不要附带单位或算式。'};
  const text=input.replace(/[０-９Ａ-Ｚａ-ｚ＋－．，]/g,c=>String.fromCharCode(c.charCodeAt(0)-0xfee0)).trim();
  // Commas must group thousands, never decimal separators or arbitrary punctuation.
  if(!/^[+-]?(?:(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(text))return {ok:false,message:'请填十进制数字，可用科学计数法或规范千分位；不要附带单位、百分号或算式。'};
  const normalized=text.replace(/,/g,''),value=Number(normalized);
  if(!finite(value)||decimalKey(decimal(normalized))!==decimalKey(decimal(String(value))))return {ok:false,message:'数字超出可判定精度或范围，请核对数值或参考答案。'};
  return {ok:true,value,normalized};
 }
 function grade(q,answers){
  const basis=q?.answer?.provenance==='ai'?'非官方参考判定':'按来源所列规则判定';
  const invalid=validate(q);if(invalid.length)return {kind:'self',status:'unavailable',result:'判分规则待修复，未作正确性判定',basis,errors:invalid};
  const g=q.grading||{kind:'self'};if(g.kind==='self')return {kind:'self',status:'self',result:'待参考对照 / 自评',basis};
  const fields=new Map(q.parts.flatMap(p=>p.fields).map(f=>[f.id,f])),errors=[];let correct=true;
  for(const r of g.rules){const value=answers?.[r.fieldId],f=fields.get(r.fieldId);
   if(g.kind==='numeric'){const parsed=parseNumeric(value);if(!parsed.ok){errors.push({fieldId:r.fieldId,message:(f.label||r.fieldId)+'：'+parsed.message});continue}if(!withinTolerance(parsed.value,r.expected,r.tolerance??0))correct=false}
   else{const values=options(f);if(f.kind==='choice'){if(typeof value!=='string'||!values.includes(value)){errors.push({fieldId:r.fieldId,message:(f.label||r.fieldId)+'：请选择一个有效选项。'});continue}if(value!==r.expected)correct=false}
    else{if(!Array.isArray(value)||!value.length||value.some(v=>!values.includes(v))||new Set(value).size!==value.length){errors.push({fieldId:r.fieldId,message:(f.label||r.fieldId)+'：请选择有效且不重复的选项。'});continue}if(value.length!==r.expected.length||value.some(v=>!r.expected.includes(v)))correct=false}}
  }
  if(errors.length)return {kind:g.kind,status:'invalid-input',result:'请先调整输入格式，尚未判分',basis,errors};
  return {kind:g.kind,status:correct?'correct':'incorrect',result:correct?'符合参考规则':'与参考规则不一致',basis};
 }
 const api={validate,parseNumeric,grade};if(typeof module==='object'&&module.exports)module.exports=api;else root.DTHGrading=api;
})(typeof window==='object'?window:globalThis);
