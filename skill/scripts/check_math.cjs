const fs=require('node:fs'),katex=require(process.argv[2]);
const expressions=JSON.parse(fs.readFileSync(0,'utf8'));let errors=[];
for(const [i,tex]of expressions.entries())try{katex.renderToString(tex,{throwOnError:true,trust:false,strict:'error',maxExpand:1000})}catch(e){errors.push({i,message:e.message})}
if(errors.length){console.error(JSON.stringify(errors));process.exit(1)}
console.log(JSON.stringify({checked:expressions.length}));
