import fs from 'node:fs';
import path from 'node:path';
import ts from 'typescript';

const root = path.resolve(import.meta.dirname, '../src');
const layers = ['shared', 'entities', 'features', 'widgets', 'pages', 'app'];
const errors = [];
function walk(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const file = path.join(directory, entry.name);
    return entry.isDirectory() ? walk(file) : /\.tsx?$/.test(file) ? [file] : [];
  });
}
for (const file of walk(root)) {
  const from = path.relative(root, file).replaceAll('\\', '/').split('/');
  const source = ts.createSourceFile(
    file,
    fs.readFileSync(file, 'utf8'),
    ts.ScriptTarget.Latest,
    true,
  );
  function check(node) {
    const specifier =
      ts.isImportDeclaration(node) || ts.isExportDeclaration(node)
        ? node.moduleSpecifier
        : ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword
          ? node.arguments[0]
          : null;
    if (specifier && ts.isStringLiteral(specifier)) {
      const name = specifier.text;
      const resolved = name.startsWith('@/')
        ? path.join(root, name.slice(2))
        : name.startsWith('.')
          ? path.resolve(path.dirname(file), name)
          : null;
      if (resolved) {
        const to = path.relative(root, resolved).replaceAll('\\', '/').split('/');
        const sameSlice = from[0] === to[0] && from[1] === to[1];
        const fromRank = layers.indexOf(from[0]);
        const toRank = layers.indexOf(to[0]);
        const describe = (reason) =>
          errors.push(`${path.relative(root, file)} -> ${name}: ${reason}`);
        if (fromRank >= 0 && toRank > fromRank) describe('dependency points to a higher layer');
        if (fromRank > 0 && fromRank < 5 && toRank === fromRank && !sameSlice)
          describe('cross-slice import');
        if (toRank > 0 && toRank < 5 && !sameSlice && to.length > 2)
          describe('use the slice public API');
      }
    }
    ts.forEachChild(node, check);
  }
  check(source);
}
if (errors.length) {
  console.error(errors.join('\n'));
  process.exit(1);
}
console.log('FSD import boundaries passed.');
