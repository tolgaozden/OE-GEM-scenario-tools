function T = oe_equations(forecastId, groups, opts)
%OE_EQUATIONS Equations, residual types and metadata for each indicator of some groups.
%   T = OE_EQUATIONS(FORECASTID, GROUPS) asks the model-variables endpoint
%   for every catalogue indicator in each group (GROUPS: char, string or
%   cell array) and returns a table with variables
%       indicator     indicator code
%       group         group code
%       name          indicator description from the catalogue
%       residualType  e.g. 'Additive' or 'Multiplicative' ('' if none)
%       nResiduals    number of residual entries returned
%       equation      equation text ('' for identities/exogenous series)
%       metadata      metadata as JSON text
%   FORECASTID is a forecast id or the struct from OE_RESOLVE_RELEASE.
%
%   T = OE_EQUATIONS(..., OPTS) with OPTS fields:
%       indicators         codes to ask for (default: whole catalogue)
%       batch              selections per request (default 400)
%       onlyWithEquations  drop rows without an equation (default false)
%       markdownDir        write one Markdown file per group,
%                          equations_<GROUP>.md, into this folder
%       renderMath         Markdown: add a LaTeX rendering of each
%                          equation (see OE_EQ_LATEX); the source text
%                          stays underneath (default false)
%       glossary           Markdown: append a table of every indicator
%                          code and name (default false)
%       title              label printed at the top of each Markdown file
%                          (default: the release name or forecast id)
%
%   The output files contain model content: keep them out of shared or
%   public repositories.
%
%   Example:
%       rel = oe_resolve_release('latest:5yr');
%       T = oe_equations(rel, {'US'}, struct('indicators', {{'GDP', 'C'}}, ...
%                        'markdownDir', 'equations', 'renderMath', true));
%
%   See also OE_EQ_LATEX, OE_CATALOGUE.

if nargin < 3
    opts = struct();
end
o = merge_opts(opts, struct('indicators', {{}}, 'batch', 400, 'onlyWithEquations', false, ...
    'markdownDir', '', 'renderMath', false, 'glossary', false, 'title', ''), 'oe_equations');
fid = forecast_id(forecastId);
title = char(o.title);
if isempty(title)
    title = fid;
    if isstruct(forecastId) && isfield(forecastId, 'Name') && ~isempty(forecastId.Name)
        title = char(forecastId.Name);
    end
end
if ischar(groups) || isstring(groups)
    groups = cellstr(groups);
end
groups = groups(:)';
base = ['/v1/forecast-contents/' oe_quote_path(fid)];

cat = as_records(oe_api('GET', [base '/indicators']));
catCodes = cellfun(@(r) field_text(r, 'Code'), cat, 'UniformOutput', false);
catNames = cellfun(@(r) field_text(r, 'Name'), cat, 'UniformOutput', false);
if isempty(o.indicators)
    inds = catCodes;
else
    inds = cellstr(o.indicators);
end
inds = inds(:)';
batch = max(1, round(o.batch));
url = [base '/model-variables?onlyProps=Equations,Residuals,Metadata'];

rows = cell(0, 7);
for g = 1:numel(groups)
    grp = groups{g};
    for b = 1:batch:numel(inds)
        chunk = inds(b:min(b + batch - 1, numel(inds)));
        sel = cellfun(@(c) struct('IndicatorCode', c, 'GroupCode', grp), chunk, 'UniformOutput', false);
        try
            data = oe_api('POST', url, sel);
        catch err
            warning('oe:equations', '%s: request for indicators %d-%d failed: %s', ...
                grp, b, b + numel(chunk) - 1, err.message);
            continue
        end
        recs = as_records(data);
        for i = 1:numel(recs)
            v = recs{i};
            if ~isstruct(v)
                continue
            end
            code = field_text(v, 'IndicatorCode');
            k = find(strcmp(catCodes, code), 1);
            name = '';
            if ~isempty(k)
                name = catNames{k};
            end
            eq = '';
            if isfield(v, 'Equations') && ~isempty(v.Equations)
                eq = eq_text(v.Equations);
            end
            nres = 0;
            if isfield(v, 'Residuals')
                nres = numel(v.Residuals);
            end
            meta = '';
            if isfield(v, 'Metadata') && ~isempty(v.Metadata)
                meta = jsonencode(v.Metadata);
            end
            gcode = field_text(v, 'GroupCode');
            if isempty(gcode)
                gcode = grp;
            end
            rows(end + 1, :) = {code, gcode, name, field_text(v, 'ResidualType'), nres, eq, meta}; %#ok<AGROW>
        end
    end
end

T = cell2table(rows, 'VariableNames', ...
    {'indicator', 'group', 'name', 'residualType', 'nResiduals', 'equation', 'metadata'});
if isempty(rows)
    T.nResiduals = zeros(0, 1);
end
if o.onlyWithEquations
    T = T(~cellfun(@isempty, T.equation), :);
end
if height(T) > 1
    T = sortrows(T, {'group', 'indicator'});
end

if ~isempty(o.markdownDir)
    folder = char(o.markdownDir);
    if ~isfolder(folder)
        mkdir(folder);
    end
    for g = 1:numel(groups)
        grp = groups{g};
        file = fullfile(folder, ['equations_' regexprep(grp, '[^A-Za-z0-9_-]', '_') '.md']);
        write_markdown(file, grp, title, T(strcmpi(T.group, grp), :), o, catCodes, catNames);
        fprintf('%s -> %s\n', grp, file);
    end
end
end

function s = eq_text(x)
% Readable text for the Equations payload, whatever its shape.
if isempty(x)
    s = '';
elseif ischar(x)
    s = x;
elseif isstring(x)
    s = char(strjoin(x(:), newline));
elseif iscell(x) && all(cellfun(@(e) ischar(e) || isstring(e), x))
    s = char(strjoin(string(x(:)), newline));
elseif isstruct(x)
    parts = cell(1, numel(x));
    for i = 1:numel(x)
        parts{i} = '';
        for f = {'Equation', 'Definition', 'Expression', 'Formula', 'Text'}
            if isfield(x(i), f{1})
                parts{i} = eq_text(x(i).(f{1}));
                if ~isempty(parts{i})
                    break
                end
            end
        end
        if isempty(parts{i})
            parts{i} = json_pretty(x(i));
        end
    end
    s = strjoin(parts, [newline '---' newline]);
else
    s = json_pretty(x);
end
end

function tf = looks_algebraic(s)
% Render as math only text that refers to MNEM:GROUP variables and does not
% read like prose (descriptions sometimes arrive in the Equations field).
tf = ~isempty(s) && s(1) ~= '{' && s(1) ~= '[' ...
    && ~isempty(regexp(s, '[A-Za-z][A-Za-z0-9_]*:[A-Za-z]', 'once')) ...
    && isempty(regexp(s, ' & | and |,\s*[a-z]', 'once'));
end

function m = md_text(s)
% Escape text for the Markdown body: a lone $ would otherwise open math.
m = char(s);
m = strrep(m, '\', '\\');
m = strrep(m, '$', '\$');
m = strrep(m, '*', '\*');
m = strrep(m, '_', '\_');
m = strrep(m, '`', '\`');
end

function m = md_cell(s)
m = strrep(md_text(s), '|', '\|');
m = regexprep(m, '\s*[\r\n]+\s*', ' ');
end

function write_markdown(file, grp, title, T, o, catCodes, catNames)
b = {};
b{end + 1} = ['# Model equations: ' md_text(grp)];
b{end + 1} = '';
b{end + 1} = sprintf('Forecast: %s. Written %s. %d indicators.', md_text(title), ...
    char(datetime('now', 'Format', 'yyyy-MM-dd HH:mm')), height(T));
b{end + 1} = '';
for i = 1:height(T)
    head = ['## ' md_text(T.indicator{i})];
    if ~isempty(T.name{i})
        head = [head ': ' md_text(T.name{i})]; %#ok<AGROW>
    end
    b{end + 1} = head; %#ok<AGROW>
    b{end + 1} = ''; %#ok<AGROW>
    meta = {};
    if ~isempty(T.residualType{i})
        meta{end + 1} = ['Residual: ' md_text(T.residualType{i})]; %#ok<AGROW>
    end
    if T.nResiduals(i) > 0
        meta{end + 1} = sprintf('%d residual entries', T.nResiduals(i)); %#ok<AGROW>
    end
    if ~isempty(meta)
        b{end + 1} = strjoin(meta, '; '); %#ok<AGROW>
        b{end + 1} = ''; %#ok<AGROW>
    end
    eq = T.equation{i};
    if isempty(eq)
        b{end + 1} = '_No equation returned (identity or exogenous series)._'; %#ok<AGROW>
    elseif o.renderMath && looks_algebraic(eq)
        b = [b, {'$$', oe_eq_latex(eq), '$$', '', '<details><summary>Source equation</summary>', '', ...
            '```text', eq, '```', '</details>'}]; %#ok<AGROW>
    else
        b = [b, {'```text', eq, '```'}]; %#ok<AGROW>
    end
    b{end + 1} = ''; %#ok<AGROW>
end
if o.glossary && ~isempty(catCodes)
    [~, order] = sort(lower(catCodes));
    b = [b, {'## Mnemonic glossary', '', '| Mnemonic | Description |', '|---|---|'}];
    for k = order(:)'
        b{end + 1} = ['| `' catCodes{k} '` | ' md_cell(catNames{k}) ' |']; %#ok<AGROW>
    end
    b{end + 1} = '';
end
write_text(file, strjoin(b, newline));
end
