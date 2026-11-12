'use strict';
const assert=require('node:assert/strict');
const grading=require('../assets/grading.js');
const numeric=()=>({parts:[{fields:[{id:'n',kind:'number',label:'数量'}]}],answer:{status:'ready',provenance:'original'},grading:{kind:'numeric',rationale:'Exact count.',rules:[{fieldId:'n',expected:1000}]}});
for(const input of ['1000',' 1000 ','1,000','１，０００','1e3','１Ｅ３','+1000','1000.0'])assert.equal(grading.grade(numeric(),{n:input}).status,'correct',input);
for(const input of ['',null,undefined,[],{},'1000元','1000%','2000/2','0x3e8','0b1111101000','10,00','1,00,000','1 000','1e999','Infinity','NaN','1e-999'])assert.equal(grading.grade(numeric(),{n:input}).status,'invalid-input',String(input));
assert.equal(grading.grade(numeric(),{n:'999'}).status,'incorrect');
for(const key of ['expected','tolerance'])for(const value of [null,true,'1000',Infinity,NaN]){const q=numeric();q.grading.rules[0][key]=value;assert.equal(grading.grade(q,{n:'7'}).status,'unavailable')}
let q=numeric();delete q.grading.rules[0].expected;assert.equal(grading.grade(q,{n:'7'}).status,'unavailable');
q=numeric();q.grading.rules[0].tolerance=-1;assert.equal(grading.grade(q,{n:'7'}).status,'unavailable');
q=numeric();q.grading.rules[0].tolerance=.1;assert.equal(grading.grade(q,{n:'1000.05'}).status,'correct');
q=numeric();q.parts[0].fields.push({id:'extra',kind:'number'});assert.equal(grading.grade(q,{n:'1000',extra:'5'}).status,'unavailable');
q=numeric();q.parts[0].fields[0]={id:'n',kind:'multiple',options:[{value:'a'},{value:'b'},{value:'c'}]};q.grading={kind:'choice',rationale:'Source choices.',rules:[{fieldId:'n',expected:['b','a']}]};
assert.equal(grading.grade(q,{n:['a','b']}).status,'correct');assert.equal(grading.grade(q,{n:['c']}).status,'incorrect');assert.equal(grading.grade(q,{n:['x']}).status,'invalid-input');assert.equal(grading.grade(q,{n:['a','a']}).status,'invalid-input');
q.grading.rules[0].expected=['x'];assert.equal(grading.grade(q,{n:['a']}).status,'unavailable');
assert.equal(grading.grade({answer:{status:'ready'},grading:{kind:'self'}},{n:'x'}).status,'self');
for(const [expected,input]of[[.1,'0.100000000000000001'],[5e-324,'4e-324'],[1000,'9007199254740993']]){q=numeric();q.grading.rules[0].expected=expected;assert.equal(grading.grade(q,{n:input}).status,'invalid-input')}
q=numeric();q.grading.rules[0].expected=9007199254740992;assert.equal(grading.grade(q,{n:'9007199254740993'}).status,'unavailable');
for(const [expected,tolerance,input]of[[.7,.2,'.9'],[1.2,.1,'1.3']]){q=numeric();q.grading.rules[0]={fieldId:'n',expected,tolerance};assert.equal(grading.grade(q,{n:input}).status,'correct')}
q=numeric();q.grading.rules[0]={fieldId:'n',expected:.7,tolerance:.2};assert.equal(grading.grade(q,{n:'.9000000000000001'}).status,'incorrect');
q=numeric();q.grading.rules[0]={fieldId:'n',expected:5e-324,tolerance:0};assert.equal(grading.grade(q,{n:'5e-324'}).status,'correct');
console.log('grading edge cases passed');
