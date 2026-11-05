/** Compare official code typography without conflating arbitrary project document labels. */
export function standardVersionKey(value:string):string {
 const text=value.trim().toUpperCase();
 return /^(GB|JTG|CJJ|TB|DB|JGJ)\s*[-/]?\s*T?\s*[A-Z0-9.]/.test(text)?text.replace(/[^A-Z0-9]/g,''):value.trim();
}
