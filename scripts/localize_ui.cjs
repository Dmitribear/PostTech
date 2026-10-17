// One-time AST codemod: translate UI text at render time; never mutate the DOM.
const ts=require('../frontend/node_modules/typescript');
const fs=require('fs');const path=require('path');
const root=path.resolve(__dirname,'../frontend/src');const catalogue=new Set();
function visitFile(file){
 let source=fs.readFileSync(file,'utf8');const sf=ts.createSourceFile(file,source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);const edits=[];
 function visit(n){
  if(ts.isStringLiteral(n)&&/[А-Яа-яЁё]/.test(n.text))catalogue.add(n.text.trim().replace(/\s+/g,' '));
  if(ts.isJsxText(n)&&/[А-Яа-яЁё]/.test(n.text)){
   const value=n.text.replace(/\s+/g,' ');catalogue.add(value.trim());edits.push([n.pos,n.end,'{t('+JSON.stringify(value)+')}']);return;
  }
  if(ts.isJsxAttribute(n)&&n.initializer&&ts.isStringLiteral(n.initializer)&&/[А-Яа-яЁё]/.test(n.initializer.text)){
   catalogue.add(n.initializer.text.trim());edits.push([n.initializer.getStart(sf),n.initializer.end,'{t('+JSON.stringify(n.initializer.text)+')}']);return;
  }
  // Expressions rendered as children; tx preserves React nodes, numbers and booleans.
  if(ts.isJsxExpression(n)&&n.expression&&!ts.isJsxAttribute(n.parent)&&!ts.isJsxSpreadAttribute(n.parent)){
   const e=n.expression;const raw=e.getText(sf);
   // Never translate user text, personal data, or the source document itself.
   if(!/\.(?:comment|reviewer_comment|answer|content|context|question|text|full_name|email|reason|material_markdown)\b/.test(raw)&&!raw.startsWith('tx(')&&!raw.startsWith('t(')){
    edits.push([e.getStart(sf),e.getStart(sf),'tx('],[e.end,e.end,')']);
   }
  }
  ts.forEachChild(n,visit);
 }
 visit(sf);
 if(edits.length){for(const [start,end,text] of edits.sort((a,b)=>b[0]-a[0]||b[1]-a[1]))source=source.slice(0,start)+text+source.slice(end);
  const rel=path.relative(path.dirname(file),path.join(root,'lib/i18n')).replaceAll('\\','/');source=`import { t, tx } from '${rel.startsWith('.')?rel:'./'+rel}';\n`+source;fs.writeFileSync(file,source);}
}
for(const dir of ['pages','components'])for(const name of fs.readdirSync(path.join(root,dir)))if(name.endsWith('.tsx'))visitFile(path.join(root,dir,name));
visitFile(path.join(root,'App.tsx'));
fs.writeFileSync(path.resolve(__dirname,'../.local/ui-catalogue.json'),JSON.stringify([...catalogue].sort(),null,2));
