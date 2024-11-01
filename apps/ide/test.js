// parse_ast.js
const fs = require('fs');
const esprima = require('esprima');

function parseFileToAST(filePath) {
    const code = fs.readFileSync(filePath, 'utf-8');
    // Parse the file code into AST format
    const ast = esprima.parseModule(code, { jsx: true, tolerant: true });
    return ast;
}

// Write the AST to a JSON file
const [,, filePath, outputPath] = process.argv;
const ast = parseFileToAST(filePath);
fs.writeFileSync(outputPath, JSON.stringify(ast, null, 2));
console.log(`AST for ${filePath} saved to ${outputPath}`);
