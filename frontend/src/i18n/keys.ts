/**
 * E8-13: find every UI string that needs a translation, by reading the source with the
 * TypeScript compiler. Used by the completeness test and by `npm run i18n:keys`.
 *   - the first argument of every tr("…") call
 *   - any other Thai string/template literal (labels in module-level tables, rendered via tr(label))
 *   - Thai JSX text that is NOT wrapped in tr() — reported as untranslated
 */
import fs from "node:fs";
import path from "node:path";
import ts from "typescript";

const THAI = /[฀-๿]/;
const SKIP = [/schema\.d\.ts$/, /\.test\.tsx?$/, /[\\/]i18n[\\/]/, /lib[\\/]i18n\.ts$/, /pages[\\/]DesignSystem\.tsx$/];

export type KeyUse = { key: string; where: string };

function files(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) return files(p);
    return /\.tsx?$/.test(e.name) && !SKIP.some((r) => r.test(p)) ? [p] : [];
  });
}

const templateKey = (n: ts.TemplateExpression) =>
  n.head.text + n.templateSpans.map((s, i) => `{${i}}${s.literal.text}`).join("");

export function scan(srcDir: string): { keys: KeyUse[]; untranslated: KeyUse[] } {
  const keys: KeyUse[] = [];
  const untranslated: KeyUse[] = [];
  for (const file of files(srcDir)) {
    const text = fs.readFileSync(file, "utf8");
    const sf = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true,
      file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
    const where = (n: ts.Node) => `${path.relative(srcDir, file)}:${sf.getLineAndCharacterOfPosition(n.getStart()).line + 1}`;
    const visit = (n: ts.Node) => {
      if (ts.isImportDeclaration(n)) return;
      if (ts.isJsxText(n) && THAI.test(n.text)) untranslated.push({ key: n.text.trim(), where: where(n) });
      if ((ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n)) && THAI.test(n.text)) keys.push({ key: n.text, where: where(n) });
      if (ts.isTemplateExpression(n) && THAI.test(templateKey(n))) {
        const p = n.parent;
        const inTr = ts.isCallExpression(p) && ts.isIdentifier(p.expression) && p.expression.text === "tr";
        (inTr ? keys : untranslated).push({ key: templateKey(n), where: where(n) });
      }
      ts.forEachChild(n, visit);
    };
    visit(sf);
  }
  return { keys, untranslated };
}
