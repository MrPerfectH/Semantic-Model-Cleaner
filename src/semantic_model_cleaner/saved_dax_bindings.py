"""Bounded saved-query binding tree; not a DAX evaluator or type checker.

Schemas are propagated only for explicitly supported table functions. Every
body is visited, including unused variables and query measures. Unknown row
schemas and ambiguous virtual ownership are errors, never global name filters.
"""
from dataclasses import dataclass, field

from .saved_dax import DaxBindingError, DaxCoverageError, covered_tokens


@dataclass
class Node:
    kind: str
    value: str = ""
    children: list = field(default_factory=list)
    position: int = 0


class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.i = 0

    def word(self, value):
        return (self.i < len(self.tokens) and self.tokens[self.i].kind == "identifier"
                and self.tokens[self.i].value.casefold() == value)

    def at(self, value):
        return self.i < len(self.tokens) and self.tokens[self.i].value == value

    def take(self, value):
        if not self.at(value):
            raise DaxCoverageError("Unsupported binding syntax: expected " + value)
        self.i += 1

    def expression(self):
        node = self.primary()
        # Precedence has no effect on dependency union. Operators never convey
        # table schemas; grouping, call arguments and VAR bodies remain exact.
        parts = [node]
        while self.i < len(self.tokens):
            t = self.tokens[self.i]
            operator = (t.kind == "punctuation" and t.value in "+-*/^&=<>|"
                        or t.kind == "identifier" and t.value.casefold() in {"in", "and", "or"})
            if not operator:
                break
            self.i += 1
            if t.value in "<>=&|" and self.i < len(self.tokens):
                if self.tokens[self.i].value in {"=", t.value}:
                    self.i += 1
            parts.append(self.primary())
        return node if len(parts) == 1 else Node("scalar", children=parts)

    def primary(self):
        if self.i >= len(self.tokens):
            raise DaxCoverageError("Empty expression binding.")
        t = self.tokens[self.i]
        self.i += 1
        name = t.value.casefold()
        if t.kind == "identifier" and name == "var":
            declarations = []
            while True:
                if self.i >= len(self.tokens) or self.tokens[self.i].kind != "identifier":
                    raise DaxCoverageError("Malformed local VAR binding.")
                var = self.tokens[self.i].value
                self.i += 1
                self.take("=")
                declarations.append(Node("binding", var, [self.expression()]))
                if not self.word("var"):
                    break
                self.i += 1
            if not self.word("return"):
                raise DaxCoverageError("Local VAR binding requires RETURN.")
            self.i += 1
            return Node("let", children=declarations + [self.expression()])
        if t.value in {"+", "-"} or t.kind == "identifier" and name == "not" and not self.at("("):
            return Node("scalar", children=[self.primary()])
        if t.value == "(":
            child = self.expression()
            # Parenthesized tuples in table constructors.
            children = [child]
            while self.at(","):
                self.i += 1
                children.append(self.expression())
            self.take(")")
            return child if len(children) == 1 else Node("tuple", children=children)
        if t.value == "{":
            children = []
            if not self.at("}"):
                children.append(self.expression())
                while self.at(","):
                    self.i += 1
                    children.append(self.expression())
            self.take("}")
            return Node("constructor", children=children, position=t.start)
        if t.kind == "string":
            return Node("literal", t.value)
        if t.kind == "punctuation" and t.value.isdigit():
            end = t.end
            while self.i < len(self.tokens):
                nxt = self.tokens[self.i]
                if nxt.start != end or nxt.kind != "punctuation" or nxt.value not in "0123456789.":
                    break
                end = nxt.end
                self.i += 1
            return Node("literal")
        if t.kind == "object":
            return Node("ref", t.value)
        if t.kind in {"identifier", "table"}:
            if self.i < len(self.tokens) and self.tokens[self.i].kind == "object":
                obj = self.tokens[self.i]
                self.i += 1
                return Node("qualified", t.value, [Node("ref", obj.value)])
            if t.kind == "identifier" and self.at("("):
                self.i += 1
                args = []
                if not self.at(")"):
                    args.append(self.expression())
                    while self.at(","):
                        self.i += 1
                        # DAX allows omitted optional scalar arguments.
                        args.append(Node("literal") if self.at(")") or self.at(",") else self.expression())
                self.take(")")
                return Node("call", name, args, t.start)
            if t.kind == "identifier" and name in {"true", "false", "asc", "desc"}:
                return Node("literal")
            if t.kind == "identifier" and name in {
                    "evaluate", "define", "measure", "return", "order", "by", "start", "at",
                    "table", "column", "function"}:
                raise DaxCoverageError("Unsupported binding keyword: " + t.value)
            return Node("table" if t.kind == "table" else "name", t.value)
        raise DaxCoverageError("Unsupported expression binding: " + t.value)

    def query(self):
        measures, variables, evaluations = [], [], []
        if self.word("define"):
            self.i += 1
            while not self.word("evaluate") and self.i < len(self.tokens):
                if self.word("measure"):
                    self.i += 1
                    owner = self.tokens[self.i] if self.i < len(self.tokens) else None
                    if owner is None or owner.kind not in {"identifier", "table"}:
                        raise DaxCoverageError("Malformed DEFINE MEASURE owner binding.")
                    self.i += 1
                    obj = self.tokens[self.i] if self.i < len(self.tokens) else None
                    if obj is None or obj.kind != "object":
                        raise DaxCoverageError("Malformed DEFINE MEASURE binding.")
                    self.i += 1
                    self.take("=")
                    measures.append((owner.value, obj.value, self.expression()))
                elif self.word("var"):
                    self.i += 1
                    if self.i >= len(self.tokens) or self.tokens[self.i].kind != "identifier":
                        raise DaxCoverageError("Malformed DEFINE VAR binding.")
                    name = self.tokens[self.i].value
                    self.i += 1
                    self.take("=")
                    variables.append((name, self.expression()))
                else:
                    raise DaxCoverageError("Unsupported DEFINE binding.")
            if not measures and not variables:
                raise DaxCoverageError("Empty DEFINE binding.")
        while self.word("evaluate"):
            self.i += 1
            result = self.expression()
            order = []
            if self.word("order"):
                self.i += 1
                if not self.word("by"):
                    raise DaxCoverageError("ORDER binding requires BY.")
                self.i += 1
                while True:
                    order.append(self.expression())
                    if self.word("asc") or self.word("desc"):
                        self.i += 1
                    if not self.at(","):
                        break
                    self.i += 1
            if self.word("start"):
                self.i += 1
                if not self.word("at"):
                    raise DaxCoverageError("START binding requires AT.")
                self.i += 1
                order.append(self.expression())
                while self.at(","):
                    self.i += 1
                    order.append(self.expression())
            evaluations.append((result, order))
        if not evaluations or self.i != len(self.tokens):
            raise DaxCoverageError("Unsupported query binding or missing EVALUATE.")
        return measures, variables, evaluations


@dataclass
class Shape:
    columns: dict = field(default_factory=dict)
    kind: str = "scalar"

    @classmethod
    def merge(cls, shapes):
        columns = {}
        for shape in shapes:
            for name, origins in shape.columns.items():
                columns.setdefault(name, set()).update(origins)
        return cls(columns, "table")


class Binder:
    def __init__(self, measures, items):
        self.refs = []
        self.locals = set()
        self.items = list(items) if items is not None else None
        self.tables = {}
        self.objects = {}
        for item in self.items or []:
            key = (item.table.casefold(), item.name.casefold())
            self.objects.setdefault(key, []).append(item)
            if item.source_kind == "model":
                self.tables.setdefault(item.table.casefold(), []).append(item)
        missing_owners = []
        for table, name, _ in measures:
            key = (table.casefold(), name.casefold())
            if key in self.locals or any(n == key[1] for _, n in self.locals):
                raise DaxCoverageError("Ambiguous duplicate DEFINE MEASURE name.")
            self.locals.add(key)
            if (table, None) not in self.refs:
                self.refs.append((table, None))
            if self.items is not None and table.casefold() not in self.tables:
                missing_owners.append(table)
        if missing_owners:
            raise DaxBindingError("DEFINE MEASURE owner table cannot be resolved: "
                                  + ", ".join(sorted(set(missing_owners), key=str.casefold)))

    def external(self, table, name):
        if self.items is not None:
            matches = [item for (t, n), values in self.objects.items()
                       if n == name.casefold() and (table is None or t == table.casefold())
                       for item in values]
            if not matches:
                # Engine-generated helpers are not persisted source objects.
                # Detect only an exact native measure owner with dynamic-format
                # metadata. Lineage/runtime binding remains unsupported, so no
                # reference is accepted or cleanup coverage relaxed here.
                folded = name.casefold()
                if folded.startswith("_") and folded.endswith(" formatstring"):
                    owner_name = folded[1:-len(" formatstring")]
                    owners = [item for (t, n), values in self.objects.items()
                              if n == owner_name and (table is None or t == table.casefold())
                              for item in values if item.source_kind == "model"
                              and item.item_type == "Measure"
                              and item.format_string_expression.strip()]
                    if owners:
                        raise DaxCoverageError(
                            "Unsupported generated dynamic-format binding: "
                            + (table or "") + "[" + name + "]"
                            + "; native owner formatStringDefinition exists; "
                            + "generated lineage and runtime binding are not verified.")
                raise DaxBindingError("Unresolved object binding: " + (table or "") + "[" + name + "]")
            identities = {(i.source_kind, i.table.casefold(), i.name.casefold()) for i in matches}
            if len(identities) > 1:
                raise DaxBindingError("Ambiguous external object binding: " + (table or "") + "[" + name + "]")
        self.refs.append((table, name))

    def table(self, name):
        if self.items is not None and name.casefold() not in self.tables:
            raise DaxBindingError("Unresolved table or identifier binding: " + name)
        self.refs.append((name, None))
        columns = {i.name.casefold(): {("model", name.casefold(), i.name.casefold())}
                   for i in self.tables.get(name.casefold(), [])
                   if i.item_type in {"Column", "Calculated Column", "CalculatedColumn"}}
        return Shape(columns, "table")

    def visit(self, node, env, context=None):
        context = context or Shape()
        kind, name, args = node.kind, node.value, node.children
        if kind == "let":
            scope = dict(env)
            declared = set()
            for binding in args[:-1]:
                key = binding.value.casefold()
                if key in declared:
                    raise DaxCoverageError("Ambiguous duplicate local VAR binding.")
                # Do not resolve self/forward locals as model tables.
                blocked = {b.value.casefold() for b in args[:-1]} - declared
                value = self.visit(binding.children[0], {**scope, **{k: None for k in blocked}}, context)
                scope[key] = value
                declared.add(key)
            return self.visit(args[-1], scope, context)
        if kind in {"name", "table"}:
            key = name.casefold()
            if kind == "name" and key in env:
                if env[key] is None:
                    raise DaxCoverageError("Self or forward VAR binding: " + name)
                return env[key]
            return self.table(name)
        if kind == "qualified":
            obj = args[0].value
            if name.casefold() in env:
                raise DaxCoverageError("Qualified VAR/model collision binding: " + name)
            if (name.casefold(), obj.casefold()) not in self.locals:
                self.external(name, obj)
            return Shape({obj.casefold(): {("model", name.casefold(), obj.casefold())}}, "column")
        if kind == "ref":
            origins = context.columns.get(name.casefold())
            if origins:
                if len(origins) != 1:
                    raise DaxCoverageError("Ambiguous virtual/column binding: " + name)
                if any(n == name.casefold() for _, n in self.locals):
                    raise DaxCoverageError("Ambiguous query measure/column binding: " + name)
                # DAX column/measure name precedence is not established by
                # this symbolic binder. Never silently discard a same-name
                # measure merely because a native or virtual row column exists.
                if any(
                        n == name.casefold() and any(i.item_type == "Measure" for i in values)
                        for (_, n), values in self.objects.items()):
                    raise DaxCoverageError("Ambiguous model/report measure/row column binding: " + name)
                return Shape({name.casefold(): origins}, "column")
            if not any(n == name.casefold() for _, n in self.locals):
                self.external(None, name)
            return Shape({name.casefold(): {("unqualified", name.casefold())}}, "column")
        if kind == "literal":
            return Shape()
        if kind == "tuple" or kind == "constructor" and any(arg.kind == "tuple" for arg in args):
            raise DaxCoverageError("Unsupported multi-column tuple binding.")
        if kind in {"scalar", "constructor"}:
            for arg in args:
                self.visit(arg, env, context)
            return Shape({"value": {("virtual", node.position, "value")}}, "table") if kind == "constructor" else Shape()
        if kind != "call":
            raise DaxCoverageError("Unsupported binding node.")
        return self.call(node, env, context)

    def call(self, node, env, context):
        name, args = node.value, node.children
        def visit(arg, ctx=context):
            return self.visit(arg, env, ctx)
        def table(arg):
            shape = visit(arg)
            if shape.kind != "table":
                raise DaxCoverageError("Unsupported table schema binding in " + name)
            return shape
        def alias(arg):
            if arg.kind != "literal" or not arg.value:
                raise DaxCoverageError("Virtual column binding requires a literal name in " + name)
            return arg.value.casefold()
        def add_alias(shape, arg):
            key = alias(arg)
            if key in shape.columns:
                raise DaxCoverageError("Ambiguous duplicate virtual column binding: " + key)
            shape.columns[key] = {("virtual", node.position, key)}
        def pairs(start, output, row):
            if (len(args) - start) % 2:
                raise DaxCoverageError("Unsupported name/expression binding in " + name)
            for n in range(start, len(args), 2):
                visit(args[n + 1], row)
                add_alias(output, args[n])
            return output

        if name in {"row", "addcolumns", "selectcolumns"}:
            if name == "row":
                return pairs(0, Shape(kind="table"), context)
            if not args:
                raise DaxCoverageError("Missing table binding in " + name)
            source = table(args[0])
            output = Shape.merge([source]) if name == "addcolumns" else Shape(kind="table")
            return pairs(1, output, Shape.merge([context, source]))
        if name in {"summarize", "summarizecolumns"}:
            if not args:
                raise DaxCoverageError("Missing grouping binding.")
            source = table(args[0]) if name == "summarize" else Shape(kind="table")
            output = Shape(kind="table")
            i = 1 if name == "summarize" else 0
            while i < len(args) and args[i].kind != "literal":
                shape = visit(args[i], Shape.merge([context, source]))
                if shape.kind in {"column", "group"}:
                    output = Shape.merge([output, shape])
                i += 1
            return pairs(i, output, Shape.merge([context, source]))
        if name in {"rollupgroup", "rollup", "rollupaddissubtotal"}:
            shapes = []
            output = Shape(kind="group")
            for arg in args:
                if arg.kind == "literal":
                    if name != "rollupaddissubtotal":
                        raise DaxCoverageError("Unsupported rollup binding.")
                    add_alias(output, arg)
                else:
                    shapes.append(visit(arg))
            output = Shape.merge([output, *shapes])
            output.kind = "group"
            return output
        if name == "addmissingitems":
            source_index = None
            shapes = []
            for i, arg in enumerate(args):
                shape = visit(arg)
                shapes.append(shape)
                if shape.kind == "table":
                    source_index = i
                    break
            if source_index is None:
                raise DaxCoverageError("Unsupported ADDMISSINGITEMS table binding.")
            source = shapes[-1]
            for arg in args[source_index + 1:]:
                visit(arg, Shape.merge([context, source]))
            return source
        if name in {"filter", "topn", "sumx", "averagex", "minx", "maxx", "countx",
                    "countax", "productx", "medianx", "rankx", "concatenatex"}:
            index = 1 if name == "topn" else 0
            if len(args) <= index:
                raise DaxCoverageError("Missing iterator table binding in " + name)
            source = table(args[index])
            row = Shape.merge([context, source])
            # Zero-based expression positions only. Scalar options are evaluated
            # in the caller context, which can itself contain an outer row.
            # RANKX value/order/ties must not inherit its expression's row.
            row_args = {1}
            if name == "topn":
                row_args = set(range(2, len(args), 2))
            elif name == "concatenatex":
                row_args |= set(range(3, len(args), 2))
            for i, arg in enumerate(args):
                if i != index:
                    visit(arg, row if i in row_args else context)
            return source if name in {"filter", "topn"} else Shape()
        if name in {"naturalinnerjoin", "naturalleftouterjoin", "crossjoin", "generate", "generateall"}:
            if len(args) < 2:
                raise DaxCoverageError("Missing join table binding.")
            shapes = []
            for arg in args:
                shapes.append(table(arg))
            output = Shape.merge(shapes)
            if any(len(origins) > 1 for origins in output.columns.values()):
                raise DaxCoverageError("Ambiguous join column binding.")
            return output
        if name == "substitutewithindex":
            if len(args) < 3:
                raise DaxCoverageError("Missing SUBSTITUTEWITHINDEX table binding.")
            left, right = table(args[0]), table(args[2])
            for i, arg in enumerate(args[3:], 3):
                visit(arg, Shape.merge([context, right]) if i % 2 else context)
            output = Shape({key: origins for key, origins in left.columns.items()
                            if key not in right.columns}, "table")
            add_alias(output, args[1])
            return output
        if name in {"calculatetable", "keepfilters", "all", "allselected", "allnoblankrow",
                    "values", "distinct", "filters", "allexcept"}:
            if not args:
                # ALL() clears context but provides no statically bound schema.
                return Shape()
            first = visit(args[0])
            for arg in args[1:]:
                visit(arg)
            if first.kind not in {"table", "column"}:
                raise DaxCoverageError("Unsupported table result binding in " + name)
            return Shape(dict(first.columns), "table")
        if name in {"union", "intersect", "except"}:
            shapes = [table(arg) for arg in args]
            if not shapes or any(len(s.columns) != len(shapes[0].columns) for s in shapes):
                raise DaxCoverageError("Unsupported set-operation schema binding.")
            # Output names come from the first operand. All source dependencies
            # were already visited; synthetic output origins avoid false lineage.
            return Shape({key: {("virtual", node.position, key)} for key in shapes[0].columns}, "table")
        for arg in args:
            visit(arg)
        # Known scalar functions expose references through their arguments.
        # Other table functions cannot be used as a proven row schema.
        return Shape()


def bind_query(text, items=None):
    tokens = covered_tokens(text)
    if not tokens:
        return []
    measures, variables, evaluations = Parser(tokens).query()
    binder = Binder(measures, items)
    env = {name.casefold(): None for name, _ in variables}
    seen = set()
    for name, body in variables:
        key = name.casefold()
        if key in seen:
            raise DaxCoverageError("Ambiguous duplicate DEFINE VAR binding.")
        env[key] = binder.visit(body, env)
        seen.add(key)
    for _, _, body in measures:
        binder.visit(body, env)
    for body, order in evaluations:
        shape = binder.visit(body, env)
        if order and shape.kind != "table":
            raise DaxCoverageError("Unsupported EVALUATE output schema binding for ORDER BY.")
        for expression in order:
            binder.visit(expression, env, shape)
    return binder.refs
