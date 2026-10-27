// Node's test runner avoids optional bundler bindings; all production imports stay real.
import { registerHooks } from 'node:module';
import { readFileSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
import ts from 'typescript';

registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier === 'server-only') return { url: 'data:text/javascript,export{}', shortCircuit: true };
    if (specifier.startsWith('@/')) {
      const base = resolve(process.cwd(), 'src', specifier.slice(2));
      const file = [base, base+'.ts', base+'.tsx', resolve(base, 'index.ts')].find((file) => existsSync(file));
      if (!file) throw new Error('Unresolved application import: '+specifier);
      return { url: pathToFileURL(file).href, shortCircuit: true };
    }
    return nextResolve(specifier, context);
  },
  load(url, context, nextLoad) {
    if (url.startsWith('file:') && /\.tsx?$/.test(fileURLToPath(url)) && !url.includes('/node_modules/')) {
      return { format: 'module', shortCircuit: true, source: ts.transpileModule(readFileSync(fileURLToPath(url),'utf8'), {
        compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
        fileName: fileURLToPath(url),
      }).outputText };
    }
    return nextLoad(url, context);
  },
});
