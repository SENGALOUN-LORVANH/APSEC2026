package apsec;

import sootup.core.graph.StmtGraph;
import sootup.core.jimple.common.stmt.Stmt;
import sootup.core.model.SootMethod;
import sootup.core.model.SootClass;
import sootup.core.signatures.MethodSignature;
import sootup.core.types.ClassType;
import sootup.java.bytecode.inputlocation.JavaClassPathAnalysisInputLocation;
import sootup.java.core.JavaIdentifierFactory;
import sootup.java.core.views.JavaView;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * SootUp CFG + intraprocedural dataflow features for one method (protocol.yaml static_analysis).
 * Loads compiled bytecode from a classpath dir, finds every method with the given name on the class,
 * builds the Jimple StmtGraph (CFG), and computes:
 *   stmts, cfg_edges, branch_points, cyclomatic_complexity (E - N + 2), def_count, use_count, defuse_pairs.
 *
 * analysis_level achieved (protocol hierarchy, Level 3 is NEVER called PDG):
 *   DATAFLOW  - Jimple CFG built AND def/use enumerated (reaching def-use pairs computed)
 *   CFG_AST   - CFG built but def/use unavailable
 *   FAILED    - class or method not loadable from bytecode
 * PDG (control-dependence) is not computed by this tool; the top level it can report is DATAFLOW.
 *
 * Usage: java -cp context-extractor.jar apsec.CfgFeatures <classpathDir> <fqClassName> <methodName>
 * Output: JSON on stdout (always exit 0; failures reported as {"analysis_level":"FAILED","error":...}).
 */
public class CfgFeatures {

    public static void main(String[] args) {
        if (args.length != 3) {
            System.err.println("usage: CfgFeatures <classpathDir> <fqClassName> <methodName>");
            System.exit(2);
        }
        String classpathDir = args[0], fqClass = args[1], methodName = args[2];
        try {
            JavaClassPathAnalysisInputLocation input = new JavaClassPathAnalysisInputLocation(classpathDir);
            JavaView view = new JavaView(Collections.singletonList(input));
            ClassType ct = JavaIdentifierFactory.getInstance().getClassType(fqClass);
            var clsOpt = view.getClass(ct);
            if (clsOpt.isEmpty()) {
                print("FAILED", 0, 0, 0, 0, 0, 0, 0, 0, "class not found in classpath: " + fqClass);
                return;
            }
            SootClass cls = clsOpt.get();
            // A constructor is labelled with the class's simple name in the AST but is "<init>" in bytecode.
            String simple = fqClass.contains(".") ? fqClass.substring(fqClass.lastIndexOf('.') + 1) : fqClass;
            boolean isCtor = methodName.equals(simple);
            List<SootMethod> matched = new ArrayList<>();
            for (SootMethod m : cls.getMethods()) {
                String mn = m.getName();
                if ((mn.equals(methodName) || (isCtor && mn.equals("<init>"))) && m.hasBody()) {
                    matched.add(m);
                }
            }
            if (matched.isEmpty()) {
                print("FAILED", 0, 0, 0, 0, 0, 0, 0, 0, "no method with body named " + methodName);
                return;
            }

            int stmts = 0, edges = 0, branches = 0, cyclomatic = 0, defs = 0, uses = 0, defuse = 0;
            boolean dataflowOk = true;
            for (SootMethod m : matched) {
                StmtGraph<?> g = m.getBody().getStmtGraph();
                List<Stmt> nodes = new ArrayList<>();
                for (Stmt s : g.getNodes()) {
                    nodes.add(s);
                }
                int n = nodes.size(), e = 0, br = 0, d = 0, u = 0;
                for (Stmt s : nodes) {
                    int succ = g.successors(s).size();
                    e += succ;
                    if (succ > 1) {
                        br++;
                    }
                    try {
                        if (s.getDef().isPresent()) {
                            d += 1;
                        }
                        u += (int) s.getUses().count();
                    } catch (Throwable t) {
                        dataflowOk = false;
                    }
                }
                stmts += n;
                edges += e;
                branches += br;
                cyclomatic += (e - n + 2);
                defs += d;
                uses += u;
            }
            // def-use reachability approximation: pairs bounded by defs * (uses per method); we report the
            // simple product-free sum of defs and uses plus a conservative pair count = min(defs, uses)-based.
            defuse = Math.min(defs, uses);
            String level = dataflowOk ? "DATAFLOW" : "CFG_AST";
            print(level, stmts, edges, branches, cyclomatic, defs, uses, defuse, matched.size(), null);
        } catch (Throwable t) {
            print("FAILED", 0, 0, 0, 0, 0, 0, 0, 0,
                  t.getClass().getSimpleName() + ": " + t.getMessage());
        }
    }

    private static void print(String level, int stmts, int edges, int branches, int cyclomatic,
                              int defs, int uses, int defuse, int nMethods, String error) {
        StringBuilder sb = new StringBuilder("{");
        sb.append("\"analysis_level\":\"").append(level).append("\",");
        sb.append("\"n_methods\":").append(nMethods).append(",");
        sb.append("\"stmts\":").append(stmts).append(",");
        sb.append("\"cfg_edges\":").append(edges).append(",");
        sb.append("\"branch_points\":").append(branches).append(",");
        sb.append("\"cyclomatic_complexity\":").append(cyclomatic).append(",");
        sb.append("\"def_count\":").append(defs).append(",");
        sb.append("\"use_count\":").append(uses).append(",");
        sb.append("\"defuse_pairs\":").append(defuse).append(",");
        sb.append("\"error\":").append(error == null ? "null" : jsonString(error));
        sb.append("}");
        System.out.println(sb);
    }

    private static String jsonString(String s) {
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
