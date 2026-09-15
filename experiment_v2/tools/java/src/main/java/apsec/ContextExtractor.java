package apsec;

import com.github.javaparser.StaticJavaParser;
import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.ImportDeclaration;
import com.github.javaparser.ast.Node;
import com.github.javaparser.ast.body.ClassOrInterfaceDeclaration;
import com.github.javaparser.ast.body.MethodDeclaration;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

/**
 * Thin context extractor for RQ condition C (Step 9). Given a buggy-checkout Java source file and the
 * changed line ranges from the candidate diff, finds the enclosing method(s), the containing class
 * declaration line, and the file's imports. Does not yet resolve referenced fields or direct helper
 * methods (protocol context_priority items 5-6) -- deferred; see reports/CONTEXT_EXTRACTOR_NOTES.md.
 *
 * Usage: java -jar context-extractor.jar <javaFile> <lineRangesCsv e.g. "695-701,978-984">
 * Output: JSON on stdout. On any parse/IO failure, prints {"error": "..."} and exits 1 (never crashes silently).
 */
public class ContextExtractor {

    public static void main(String[] args) {
        if (args.length != 2) {
            System.err.println("usage: ContextExtractor <javaFile> <lineRangesCsv>");
            System.exit(2);
        }
        try {
            String source = new String(Files.readAllBytes(Paths.get(args[0])), StandardCharsets.UTF_8);
            List<int[]> ranges = parseRanges(args[1]);
            CompilationUnit cu = StaticJavaParser.parse(source);

            List<String> imports = new ArrayList<>();
            for (ImportDeclaration imp : cu.getImports()) {
                imports.add(imp.toString().trim());
            }

            Optional<ClassOrInterfaceDeclaration> primaryClass = cu.findFirst(ClassOrInterfaceDeclaration.class);
            String classDeclaration = primaryClass.map(ContextExtractor::declarationLine).orElse("");

            List<MethodDeclaration> methods = cu.findAll(MethodDeclaration.class);
            List<MethodDeclaration> matched = new ArrayList<>();
            for (MethodDeclaration m : methods) {
                if (!m.getBegin().isPresent() || !m.getEnd().isPresent()) continue;
                int begin = m.getBegin().get().line;
                int end = m.getEnd().get().line;
                if (overlapsAny(begin, end, ranges)) matched.add(m);
            }

            StringBuilder out = new StringBuilder();
            out.append("{");
            out.append("\"class_declaration\":").append(jsonString(classDeclaration)).append(",");
            out.append("\"imports\":[");
            for (int i = 0; i < imports.size(); i++) {
                if (i > 0) out.append(",");
                out.append(jsonString(imports.get(i)));
            }
            out.append("],");
            out.append("\"methods\":[");
            for (int i = 0; i < matched.size(); i++) {
                if (i > 0) out.append(",");
                MethodDeclaration m = matched.get(i);
                String containingClass = m.findAncestor(ClassOrInterfaceDeclaration.class)
                        .map(c -> c.getNameAsString()).orElse("");
                String fullSource = m.toString();   // capture with javadoc before stripping the comment below
                out.append("{");
                out.append("\"containing_class\":").append(jsonString(containingClass)).append(",");
                out.append("\"signature\":").append(jsonString(signature(m))).append(",");
                out.append("\"begin_line\":").append(m.getBegin().get().line).append(",");
                out.append("\"end_line\":").append(m.getEnd().get().line).append(",");
                out.append("\"source\":").append(jsonString(fullSource));
                out.append("}");
            }
            out.append("]");
            out.append("}");
            System.out.println(out);
        } catch (Exception e) {
            System.out.println("{\"error\":" + jsonString(String.valueOf(e)) + "}");
            System.exit(1);
        }
    }

    private static String declarationLine(ClassOrInterfaceDeclaration c) {
        // Text up to (not including) the class body's opening brace: modifiers, name, generics,
        // extends/implements. The attached Javadoc must be stripped first: this codebase's Javadoc is full of
        // {@link ...} tags, whose literal '{' would otherwise be mistaken for the body's opening brace by a
        // naive indexOf('{') (observed directly on CategoryPlot.java's class-level comment).
        c.removeComment();
        return headerBefore(c.toString());
    }

    private static String signature(MethodDeclaration m) {
        m.removeComment();
        return headerBefore(m.toString());
    }

    private static String headerBefore(String nodeText) {
        int idx = nodeText.indexOf('{');
        String header = idx >= 0 ? nodeText.substring(0, idx) : nodeText.replaceAll(";\\s*$", "");
        return header.trim();
    }

    private static boolean overlapsAny(int begin, int end, List<int[]> ranges) {
        for (int[] r : ranges) {
            if (begin <= r[1] && end >= r[0]) return true;
        }
        return false;
    }

    private static List<int[]> parseRanges(String csv) {
        List<int[]> out = new ArrayList<>();
        for (String part : csv.split(",")) {
            part = part.trim();
            if (part.isEmpty()) continue;
            String[] bounds = part.split("-");
            int lo = Integer.parseInt(bounds[0].trim());
            int hi = bounds.length > 1 ? Integer.parseInt(bounds[1].trim()) : lo;
            out.add(new int[]{lo, hi});
        }
        return out;
    }

    private static String jsonString(String s) {
        if (s == null) return "null";
        StringBuilder b = new StringBuilder("\"");
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"': b.append("\\\""); break;
                case '\\': b.append("\\\\"); break;
                case '\n': b.append("\\n"); break;
                case '\r': b.append("\\r"); break;
                case '\t': b.append("\\t"); break;
                default:
                    if (c < 0x20) b.append(String.format("\\u%04x", (int) c));
                    else b.append(c);
            }
        }
        return b.append("\"").toString();
    }
}
