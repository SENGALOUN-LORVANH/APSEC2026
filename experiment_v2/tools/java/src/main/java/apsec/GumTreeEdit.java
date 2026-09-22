package apsec;

import com.github.gumtreediff.actions.ChawatheScriptGenerator;
import com.github.gumtreediff.actions.EditScript;
import com.github.gumtreediff.gen.jdt.JdtTreeGenerator;
import com.github.gumtreediff.matchers.CompositeMatchers;
import com.github.gumtreediff.matchers.MappingStore;
import com.github.gumtreediff.matchers.Matcher;
import com.github.gumtreediff.tree.Tree;
import com.github.gumtreediff.tree.TreeContext;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;

/**
 * GumTree AST S_edit (protocol.yaml scores.S_edit.primary):
 *   S_edit = min(1, gumtree_edit_actions / ast_nodes_of_changed_buggy_methods)
 *
 * Diffs the whole buggy file against the whole candidate file. Because candidate = buggy + patch, the two
 * files are identical outside the changed methods, so the edit script is already localized there -- its size
 * is the numerator. The denominator is the summed AST subtree size of the buggy MethodDeclaration nodes whose
 * source range overlaps the changed line ranges. On any failure prints {"error": "..."} and exits 1
 * (never a silent zero; the Python caller records S_edit as MISSING, per protocol analyzer_failure policy).
 *
 * Usage: java -cp context-extractor.jar apsec.GumTreeEdit <buggyFile> <candidateFile> <changedLineRangesCsv>
 * changedLineRanges are 1-based inclusive line ranges in the BUGGY file, e.g. "695-701,978-984".
 */
public class GumTreeEdit {

    public static void main(String[] args) {
        if (args.length != 3) {
            System.err.println("usage: GumTreeEdit <buggyFile> <candidateFile> <changedLineRangesCsv>");
            System.exit(2);
        }
        try {
            String buggySrc = new String(Files.readAllBytes(Paths.get(args[0])), StandardCharsets.UTF_8);
            TreeContext buggyCtx = new JdtTreeGenerator().generateFrom().string(buggySrc);
            TreeContext candCtx = new JdtTreeGenerator().generateFrom().file(args[1]);
            Tree buggyTree = buggyCtx.getRoot();
            Tree candTree = candCtx.getRoot();

            Matcher matcher = new CompositeMatchers.ClassicGumtree();
            MappingStore mappings = matcher.match(buggyTree, candTree);
            EditScript editScript = new ChawatheScriptGenerator().computeActions(mappings);
            int editActions = editScript.size();

            int[] offsets = lineStartOffsets(buggySrc);
            List<int[]> ranges = parseRanges(args[2]);
            List<String> changedMethods = new ArrayList<>();
            int astNodes = 0;
            for (Tree n : buggyTree.preOrder()) {
                if (!"MethodDeclaration".equals(n.getType().name)) {
                    continue;
                }
                int start = n.getPos();
                int end = n.getPos() + n.getLength();
                if (overlapsAnyRange(start, end, ranges, offsets)) {
                    astNodes += subtreeSize(n);
                    changedMethods.add(methodLabel(n));
                }
            }

            StringBuilder sb = new StringBuilder();
            sb.append("{");
            sb.append("\"edit_actions\":").append(editActions).append(",");
            sb.append("\"ast_nodes_changed_methods\":").append(astNodes).append(",");
            sb.append("\"n_changed_methods\":").append(changedMethods.size()).append(",");
            if (astNodes > 0) {
                double sEdit = Math.min(1.0, (double) editActions / astNodes);
                sb.append("\"s_edit_ast\":").append(sEdit).append(",");
            } else {
                sb.append("\"s_edit_ast\":null,");
            }
            sb.append("\"changed_methods\":").append(jsonStringArray(changedMethods));
            sb.append("}");
            System.out.println(sb);
        } catch (Throwable t) {
            System.out.println("{\"error\":" + jsonString(t.getClass().getSimpleName() + ": " + t.getMessage()) + "}");
            System.exit(1);
        }
    }

    private static int subtreeSize(Tree t) {
        int c = 1;
        for (Tree child : t.getChildren()) {
            c += subtreeSize(child);
        }
        return c;
    }

    private static String methodLabel(Tree methodNode) {
        for (Tree child : methodNode.getChildren()) {
            if ("SimpleName".equals(child.getType().name)) {
                return child.getLabel();
            }
        }
        return methodNode.getLabel();
    }

    private static int[] lineStartOffsets(String src) {
        List<Integer> starts = new ArrayList<>();
        starts.add(0);
        for (int i = 0; i < src.length(); i++) {
            if (src.charAt(i) == '\n') {
                starts.add(i + 1);
            }
        }
        int[] out = new int[starts.size()];
        for (int i = 0; i < out.length; i++) {
            out[i] = starts.get(i);
        }
        return out;
    }

    private static boolean overlapsAnyRange(int startOff, int endOff, List<int[]> ranges, int[] lineStarts) {
        for (int[] r : ranges) {
            int rStart = lineStarts[Math.min(r[0] - 1, lineStarts.length - 1)];
            int rEndLine = Math.min(r[1], lineStarts.length - 1);
            int rEnd = (rEndLine < lineStarts.length) ? lineStarts[rEndLine] : Integer.MAX_VALUE;
            if (startOff <= rEnd && endOff >= rStart) {
                return true;
            }
        }
        return false;
    }

    private static List<int[]> parseRanges(String csv) {
        List<int[]> ranges = new ArrayList<>();
        if (csv == null || csv.isEmpty()) {
            return ranges;
        }
        for (String part : csv.split(",")) {
            String[] se = part.trim().split("-");
            ranges.add(new int[]{Integer.parseInt(se[0].trim()), Integer.parseInt(se[se.length - 1].trim())});
        }
        return ranges;
    }

    private static String jsonStringArray(List<String> items) {
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < items.size(); i++) {
            if (i > 0) {
                sb.append(",");
            }
            sb.append(jsonString(items.get(i)));
        }
        return sb.append("]").toString();
    }

    private static String jsonString(String s) {
        if (s == null) {
            return "null";
        }
        StringBuilder sb = new StringBuilder("\"");
        for (char c : s.toCharArray()) {
            switch (c) {
                case '"': sb.append("\\\""); break;
                case '\\': sb.append("\\\\"); break;
                case '\n': sb.append("\\n"); break;
                case '\r': sb.append("\\r"); break;
                case '\t': sb.append("\\t"); break;
                default: sb.append(c);
            }
        }
        return sb.append("\"").toString();
    }
}
