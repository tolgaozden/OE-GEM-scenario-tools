function [T, manifest] = oe_run_scenarios(cfg)
%OE_RUN_SCENARIOS Solve several scenarios against one release and collect the results.
%   [T, MANIFEST] = OE_RUN_SCENARIOS(CFG) resolves the release, solves
%   every scenario against it, fetches the baseline and each solved
%   scenario into one long table T (forecast labels 'baseline' and the
%   scenario names; see OE_FETCH for the variables) and writes
%       <outDir>/results.csv        T
%       <outDir>/results.xlsx       T, sheet 'data' (if writeXlsx)
%       <outDir>/scenarios/*.3fs    the command text sent for each scenario
%       <outDir>/manifest.json      release, solve range, per-scenario status,
%                                   output path, forecast id, timing, SHA-256 of
%                                   the commands (the token is never written)
%   A scenario that fails is reported in the manifest and skipped; the
%   others still run.
%
%   CFG fields:
%       release         release spec for OE_RESOLVE_RELEASE (default 'latest:5yr')
%       solveFrom       first solve period, e.g. '2026Q3' (required)
%       solveTo         last solve period, e.g. '2031Q4' (required)
%       scenarios       struct array; each element has name and either
%                       file (a .3fs path) or commands (lines, see OE_SOLVE);
%                       an optional description goes into the manifest
%       indicators      indicator codes to fetch (required)
%       groups          group codes to fetch (required)
%       from, to        fetch window (default: everything returned)
%       outputFolder    workspace folder for the solved forecasts
%                       (default '/me'); each run uses a subfolder named
%                       after runName, created if missing
%       runName         run label (default 'run')
%       outDir          local output folder (default ./oe_runs/<runName>)
%       annualFallback  see OE_FETCH (default true)
%       writeXlsx       also write results.xlsx (default true)
%
%   Example:
%       s(1).name = 'oil_up_20pct';
%       s(1).commands = {'MULTIPLY WPO_EQN:WORLD 2027Q1 1.2, 1.2, 1.2, 1.2'; ...
%                        'FIX WPO_EQN:WORLD 2027Q1:2027Q4'};
%       cfg = struct('release', 'latest:5yr', 'solveFrom', '2026Q3', 'solveTo', '2031Q4', ...
%                    'scenarios', s, 'indicators', {{'GDP', 'CPI'}}, 'groups', {{'US', 'CHINA'}});
%       [T, manifest] = oe_run_scenarios(cfg);
%       % Mnemonics and shock sizes are illustrative: check codes in your catalogue.
%
%   See also OE_SOLVE, OE_FETCH, OE_TRANSFORM, OE_TABLE.

o = merge_opts(cfg, struct('release', 'latest:5yr', 'solveFrom', '', 'solveTo', '', 'scenarios', [], ...
    'indicators', {{}}, 'groups', {{}}, 'from', '', 'to', '', 'outputFolder', '/me', 'runName', 'run', ...
    'outDir', '', 'annualFallback', true, 'writeXlsx', true), 'oe_run_scenarios');
if isempty(o.solveFrom) || isempty(o.solveTo)
    error('oe:badInput', 'Set cfg.solveFrom and cfg.solveTo, e.g. ''2026Q3'' and ''2031Q4''.');
end
if isempty(o.indicators) || isempty(o.groups)
    error('oe:badInput', 'Set cfg.indicators and cfg.groups, e.g. {''GDP'', ''CPI''} and {''US''}.');
end
sources = check_scenarios(o.scenarios);
nScen = numel(sources);
runSlug = slug(o.runName);
outDir = char(o.outDir);
if isempty(outDir)
    outDir = fullfile(pwd, 'oe_runs', runSlug);
end
if ~isfolder(fullfile(outDir, 'scenarios'))
    mkdir(fullfile(outDir, 'scenarios'));
end
started = utc_now();

rel = oe_resolve_release(o.release);
relId = field_text(rel, 'Id');
relName = field_text(rel, 'Name');
relPath = field_text(rel, 'Path');
if isempty(relPath) || isempty(relId)
    error('oe:badInput', ['The release "%s" has no path or id. Use a release name, ''latest:5yr'' ' ...
        'or a full release path.'], char(o.release));
end
wsFolder = [regexprep(char(o.outputFolder), '/+$', '') '/' runSlug];
ensure_folder(wsFolder);

entries = cell(1, nScen);
solved = cell(1, nScen);
for s = 1:nScen
    sc = o.scenarios(s);
    name = char(sc.name);
    fprintf('\n[%d/%d] %s\n', s, nScen, name);
    try
        r = oe_solve(relPath, sources{s}, o.solveFrom, o.solveTo, ...
            struct('outputFolder', wsFolder, 'name', name));
    catch err
        warning('oe:solveFailed', 'Scenario "%s" was not solved: %s', name, err.message);
        r = struct('name', name, 'status', 'Error', 'operationId', '', 'outputPath', '', ...
            'forecastId', '', 'seconds', NaN, 'failure', err.message, 'submittedAt', '', 'commands', '');
    end
    nCmd = 0;
    if ~isempty(r.commands)
        lines = strsplit(r.commands, newline);
        nCmd = numel(lines);
        header = {['scenario: ' name], ['release: ' relName], ...
            sprintf('solve: %s:%s', char(o.solveFrom), char(o.solveTo))};
        oe_write_3fs(lines, fullfile(outDir, 'scenarios', [slug(name) '.3fs']), ...
            struct('header', {header}));
    end
    description = '';
    if isfield(sc, 'description') && ~isempty(sc.description)
        description = char(sc.description);
    end
    entries{s} = struct('name', name, 'description', description, 'status', r.status, ...
        'operation_id', r.operationId, 'output_path', r.outputPath, 'forecast_id', r.forecastId, ...
        'seconds', r.seconds, 'n_commands', nCmd, 'sha256', sha256(r.commands), 'failure', r.failure);
    solved{s} = r;
end

fetchOpts = struct('label', 'baseline', 'from', o.from, 'to', o.to, 'annualFallback', o.annualFallback);
fprintf('\nFetching baseline (%s)\n', relName);
T = oe_fetch(relId, o.indicators, o.groups, fetchOpts);
nOk = 0;
for s = 1:nScen
    r = solved{s};
    if strcmpi(r.status, 'Succeeded') && ~isempty(r.forecastId)
        fprintf('Fetching %s\n', r.name);
        fetchOpts.label = r.name;
        T = [T; oe_fetch(r.forecastId, o.indicators, o.groups, fetchOpts)]; %#ok<AGROW>
        nOk = nOk + 1;
    end
end
if height(T) > 1
    T = sortrows(T, {'forecast', 'indicator', 'group', 'period'});
end

writetable(T, fullfile(outDir, 'results.csv'));
outputs = {'results.csv'};
if o.writeXlsx
    xlsx = fullfile(outDir, 'results.xlsx');
    if isfile(xlsx)
        delete(xlsx);
    end
    writetable(T, xlsx, 'Sheet', 'data');
    outputs{end + 1} = 'results.xlsx';
end

manifest = struct( ...
    'tool', 'oe-gem-scenario-tools (MATLAB)', ...
    'run_name', char(o.runName), ...
    'started_at', started, ...
    'finished_at', utc_now(), ...
    'release', struct('name', relName, 'path', relPath, 'id', relId), ...
    'solve', struct('from', char(o.solveFrom), 'to', char(o.solveTo), 'output_folder', wsFolder), ...
    'fetch', struct('indicators', {cellstr(o.indicators)}, 'groups', {cellstr(o.groups)}, ...
        'from', char(o.from), 'to', char(o.to), 'annual_fallback', logical(o.annualFallback)), ...
    'outputs', {outputs}, ...
    'scenarios', {entries});
write_text(fullfile(outDir, 'manifest.json'), json_pretty(manifest));
fprintf('\nRun "%s": %d of %d scenario(s) solved. Results in %s\n', char(o.runName), nOk, nScen, outDir);
end

function sources = check_scenarios(scen)
% Validate every scenario before the first solve, so a typo in the last
% one does not surface after an hour of solving.
if isempty(scen) || ~isstruct(scen) || ~isfield(scen, 'name')
    error('oe:badInput', ['cfg.scenarios must be a struct array with a name and either file or ' ...
        'commands, e.g. s(1).name = ''my_case''; s(1).file = ''my_case.3fs'';']);
end
n = numel(scen);
sources = cell(1, n);
names = cell(1, n);
for k = 1:n
    names{k} = char(scen(k).name);
    if isempty(strtrim(names{k}))
        error('oe:badInput', 'Scenario %d has no name.', k);
    end
    if isfield(scen, 'file') && ~isempty(scen(k).file)
        f = char(scen(k).file);
        if ~isfile(f)
            error('oe:badInput', 'Scenario "%s": command file not found: %s', names{k}, f);
        end
        sources{k} = f;
    elseif isfield(scen, 'commands') && ~isempty(scen(k).commands)
        sources{k} = scen(k).commands;
    else
        error('oe:badInput', 'Scenario "%s" needs a file or commands.', names{k});
    end
end
slugs = lower(cellfun(@slug, names, 'UniformOutput', false));
[u, ~, idx] = unique(slugs);
if numel(u) < n
    dup = names(accumarray(idx(:), 1) > 1);
    error('oe:badInput', 'Scenario names must be unique (after replacing spaces etc.): %s', strjoin(dup, ', '));
end
end

function s = slug(name)
s = regexprep(char(name), '[^A-Za-z0-9_.-]+', '_');
end

function t = utc_now()
t = char(datetime('now', 'TimeZone', 'UTC', 'Format', 'yyyy-MM-dd''T''HH:mm:ss''Z'''));
end

function ensure_folder(path)
% Create missing workspace folders level by level. The '/me' root always
% exists; any other level is looked up first and created only if missing.
segs = strsplit(path, '/');
segs = segs(~cellfun(@isempty, segs));
lead = '';
if startsWith(path, '/')
    lead = '/';
end
for i = 1:numel(segs)
    if i == 1 && strcmpi(segs{1}, 'me')
        continue
    end
    p = [lead strjoin(segs(1:i), '/')];
    try
        oe_resource(p);
    catch err
        if strcmp(err.identifier, 'oe:http401') || ~startsWith(err.identifier, 'oe:http4')
            rethrow(err);
        end
        oe_api('PUT', ['/v1/resources/' oe_quote_path(p)], ...
            struct('Name', segs{i}, 'ResourceType', 'Directory', 'Type', 'Directory'));
        fprintf('Created workspace folder %s\n', p);
    end
end
end

function h = sha256(txt)
h = '';
if isempty(txt)
    return
end
try
    md = java.security.MessageDigest.getInstance('SHA-256');
    d = typecast(md.digest(unicode2native(txt, 'UTF-8')), 'uint8');
    h = lower(reshape(dec2hex(d, 2)', 1, []));
catch
    % no Java (matlab -nojvm): the hash is left empty
end
end
