function run_tests()
%RUN_TESTS Offline tests of the MATLAB toolkit (no network; synthetic data only).
%   RUN_TESTS runs every test below, prints one PASS/FAIL line per test and
%   a summary line, and raises an error if any test failed. All codes and
%   numbers are made up (AAA, BBB, ALPHA, BETA); nothing contacts the API:
%   the HTTP tests replace the network with a fake transport.
%
%   Example:
%       cd matlab/tests
%       run_tests

addpath(fileparts(fileparts(mfilename('fullpath'))));
tests = {@test_3fs_roundtrip, @test_3fs_compact_and_errors, @test_period_range, ...
    @test_transform_yoy, @test_transform_annual_avg, @test_transform_deviation, ...
    @test_table_pivot, @test_quote_path, @test_release_sort_key, @test_resolve_release_offline, ...
    @test_token_missing, @test_login_config_missing, @test_api_fake_transport, @test_eq_latex};
nPass = 0;
failed = {};
for i = 1:numel(tests)
    name = func2str(tests{i});
    try
        tests{i}();
        nPass = nPass + 1;
        fprintf('  PASS  %s\n', name);
    catch err
        failed{end + 1} = name; %#ok<AGROW>
        fprintf('  FAIL  %s: %s\n', name, err.message);
    end
end
fprintf('run_tests: %d passed, %d failed\n', nPass, numel(failed));
if ~isempty(failed)
    error('run_tests:failed', 'Failed tests: %s', strjoin(failed, ', '));
end
end

%% ---------------------------------------------------------------- tests

function test_3fs_roundtrip()
f = [tempname '.3fs'];
c1 = onCleanup(@() delete_if(f));
write_file(f, sprintf(['# toy scenario, synthetic codes\n' ...
    '\n' ...
    'SET AAA:ALPHA 2027Q1 1.5, 2, 2.5\r\n' ...
    'MULTIPLY BBB:ALPHA 2027Q3 3@1.1, 0.95   # inline comment\n' ...
    'INCREASE &CCC:BETA 2027 -12.5 -10\n' ...
    'FIX AAA:ALPHA 2027Q1:2027Q3\n' ...
    'unfix BBB:ALPHA 2026q4:2028Q2\n']));
cmds = oe_read_3fs(f);
assert(numel(cmds) == 5, 'expected 5 commands, got %d', numel(cmds));
assert(strcmp(cmds(1).verb, 'SET') && strcmp(cmds(1).target, 'AAA:ALPHA'));
assert(strcmp(cmds(1).start, '2027Q1') && strcmp(cmds(1).stop, '2027Q3'));
assert(isequal(cmds(1).values, [1.5 2 2.5]));
assert(isequal(cmds(2).values, [1.1 1.1 1.1 0.95]) && strcmp(cmds(2).stop, '2028Q2'));
assert(strcmp(cmds(3).target, '&CCC:BETA') && strcmp(cmds(3).start, '2027') && strcmp(cmds(3).stop, '2028'));
assert(isequal(cmds(3).values, [-12.5 -10]));
assert(strcmp(cmds(4).verb, 'FIX') && isempty(cmds(4).values) && strcmp(cmds(4).stop, '2027Q3'));
assert(strcmp(cmds(5).verb, 'UNFIX') && strcmp(cmds(5).start, '2026Q4'));

f2 = [tempname '.3fs'];
c2 = onCleanup(@() delete_if(f2));
txt = oe_write_3fs(cmds, f2, struct('header', 'round trip'));
assert(startsWith(fileread(f2), '# round trip'));
assert(contains(txt, 'MULTIPLY BBB:ALPHA 2027Q3 1.1, 1.1, 1.1, 0.95'));
assert(contains(txt, 'FIX AAA:ALPHA 2027Q1:2027Q3'));
back = oe_read_3fs(f2);
assert(isequal(back, cmds), 'write -> read did not reproduce the commands');
end

function test_3fs_compact_and_errors()
cmds = oe_read_3fs({'MULTIPLY AAA:ALPHA 2027Q1 4@1.2', 'FIX AAA:ALPHA 2027Q1:2027Q4'});
assert(isequal(cmds(1).values, repmat(1.2, 1, 4)) && strcmp(cmds(1).stop, '2027Q4'));
assert(contains(oe_write_3fs(cmds, '', struct('compact', true)), 'MULTIPLY AAA:ALPHA 2027Q1 4@1.2'));
assert(contains(oe_write_3fs(cmds), '1.2, 1.2, 1.2, 1.2'));
one = oe_read_3fs('FIX BBB:BETA 2027Q1 2027Q2');
assert(strcmp(one.start, '2027Q1') && strcmp(one.stop, '2027Q2'));
assert_error(@() oe_read_3fs({'SET AAA:ALPHA 2027Q1'}), 'oe:badCommand');
assert_error(@() oe_read_3fs({'SET AAA:ALPHA 2027Q5 1'}), 'oe:badCommand');
assert_error(@() oe_read_3fs({'SET AAA:ALPHA 2027Q1 1, x'}), 'oe:badCommand');
assert_error(@() oe_read_3fs({'FIX AAA:ALPHA 2027Q1:2027Q4 3'}), 'oe:badCommand');
assert_error(@() oe_read_3fs(fullfile(tempdir, 'no_such_file_here.3fs')), 'oe:badInput');
end

function test_period_range()
assert(isequal(oe_period_range('2026Q3', '2027Q2'), {'2026Q3'; '2026Q4'; '2027Q1'; '2027Q2'}));
assert(isequal(oe_period_range(2026, 2028), {'2026'; '2027'; '2028'}));
assert(isequal(oe_period_range('2026q4:2027q1'), {'2026Q4'; '2027Q1'}));
assert(numel(oe_period_range('2020Q1', '2031Q4')) == 48);
assert(isequal(oe_period_range('2026Q1', '2026Q1'), {'2026Q1'}));
assert_error(@() oe_period_range('2026Q1', '2027'), 'oe:badPeriod');
assert_error(@() oe_period_range('2027Q1', '2026Q4'), 'oe:badPeriod');
assert_error(@() oe_period_range('2026Q5', '2027Q1'), 'oe:badPeriod');
end

function test_transform_yoy()
T = long('baseline', 'AAA', 'ALPHA', oe_period_range('2024Q1', '2025Q4'), (100:107)');
Y = oe_transform(T, 'yoy');
assert(all(strcmp(Y.measure, 'yoy')));
assert(abs(val(Y, 'baseline', 'ALPHA', '2025Q1') - 4) < 1e-12);
assert(all(isnan(Y.value(startsWith(Y.period, '2024')))));
% a gap gives NaN, not the value of a neighbouring quarter
T2 = T(~strcmp(T.period, '2024Q2'), :);
Y2 = oe_transform(T2, 'yoy');
assert(isnan(val(Y2, 'baseline', 'ALPHA', '2025Q2')));
assert(abs(val(Y2, 'baseline', 'ALPHA', '2025Q3') - 100 * (106 / 102 - 1)) < 1e-12);
% annual series lag by one year; numeric periods (as from readtable) are accepted
A = long('baseline', 'AAA', 'BETA', {'2024'; '2025'; '2026'}, [200; 210; 231]);
A.period = [2024; 2025; 2026];
YA = oe_transform(A, 'yoy');
assert(abs(val(YA, 'baseline', 'BETA', '2026') - 10) < 1e-12);
assert(abs(val(YA, 'baseline', 'BETA', '2025') - 5) < 1e-12);
end

function test_transform_annual_avg()
T = [long('baseline', 'AAA', 'ALPHA', oe_period_range('2024Q1', '2025Q2'), [1; 2; 3; 6; 10; 20]); ...
    long('baseline', 'AAA', 'BETA', {'2024'; '2025'}, [50; 60])];
A = oe_transform(T, 'annual_avg');
assert(abs(val(A, 'baseline', 'ALPHA', '2024') - 3) < 1e-12);
assert(isnan(val(A, 'baseline', 'ALPHA', '2025')), 'an incomplete year must give NaN');
assert(val(A, 'baseline', 'BETA', '2025') == 60, 'annual rows must pass through');
assert(all(strcmp(A.freq, 'A')) && all(strcmp(A.measure, 'annual_avg')));
G = oe_transform(long('baseline', 'AAA', 'ALPHA', oe_period_range('2024Q1', '2025Q4'), ...
    [1; 2; 3; 6; 2; 4; 6; 12]), 'annual_avg|yoy');
assert(abs(val(G, 'baseline', 'ALPHA', '2025') - 100) < 1e-12);
assert(all(strcmp(G.measure, 'annual_avg|yoy')));
end

function test_transform_deviation()
P = {'2027Q1'; '2027Q2'};
T = [long('baseline', 'AAA', 'ALPHA', P, [100; 200]); long('shock', 'AAA', 'ALPHA', P, [110; 190])];
D = oe_transform(T, 'dev_abs');
assert(height(D) == 2 && all(strcmp(D.forecast, 'shock')), 'baseline rows must be dropped');
assert(isequal(D.value, [10; -10]));
Dp = oe_transform(T, 'dev_pct', 'baseline');
assert(max(abs(Dp.value - [10; -5])) < 1e-12 && all(strcmp(Dp.measure, 'dev_pct')));
C = oe_transform(T, {'yoy', 'dev_abs'});
assert(all(strcmp(C.measure, 'yoy|dev_abs')));
S = T;
S.forecast = string(S.forecast);   % string columns, as readtable can return
assert(isequal(oe_transform(S, 'dev_abs').value, [10; -10]));
assert_error(@() oe_transform(T, 'dev_abs', 'nope'), 'oe:noBaseline');
assert_error(@() oe_transform(T, 'growth'), 'oe:badStep');
end

function test_table_pivot()
P = {'2026'; '2027'};
T = [long('shock', 'AAA', 'ALPHA', P, [1; 2]); long('baseline', 'AAA', 'ALPHA', P, [3; 4]); ...
    long('baseline', 'AAA', 'BETA', P, [5; 6]); long('baseline', 'BBB', 'ALPHA', P, [7; 8])];
W = oe_table(T, 'AAA');
assert(isequal(W.Properties.VariableNames, {'group', 'forecast', '2026', '2027'}));
assert(height(W) == 3, 'expected 3 rows, got %d', height(W));
assert(strcmp(W.group{1}, 'ALPHA') && strcmp(W.forecast{1}, 'baseline'), 'baseline should come first');
assert(isequal(W{1, {'2026', '2027'}}, [3 4]) && isequal(W{2, {'2026', '2027'}}, [1 2]));
W2 = oe_table(T, 'AAA', struct('groups', {{'BETA'}}, 'to', '2026'));
assert(height(W2) == 1 && isequal(W2.Properties.VariableNames, {'group', 'forecast', '2026'}));
assert(W2.('2026') == 5);
assert_error(@() oe_table(T, 'ZZZ'), 'oe:noData');
end

function test_quote_path()
assert(strcmp(oe_quote_path('/me/my runs/test 1/'), 'me/my%20runs/test%201'));
assert(strcmp(oe_quote_path('oxford-economics/releases/Global Economic Model'), ...
    'oxford-economics/releases/Global%20Economic%20Model'));
assert(strcmp(oe_quote_path('a/Release 5yr/$Archive'), 'a/Release%205yr/%24Archive'));
assert(strcmp(oe_quote_path('x//y'), 'x/y'));
assert(strcmp(oe_quote_path(['caf' char(233)]), 'caf%C3%A9'));
assert(strcmp(oe_quote_path('a-b_c.d~e'), 'a-b_c.d~e'));
end

function test_release_sort_key()
assert(isequal(oe_release_sort_key('Sep26_2 5yr'), [2026 9 2]));
assert(isequal(oe_release_sort_key('Jun26 25yr'), [2026 6 0]));
assert(isempty(oe_release_sort_key('Notes')));
assert(isempty(oe_release_sort_key('Demo26_1 5yr')));
names = {'Jan26_1 5yr'; 'Mar26_2 5yr'; 'Mar26_10 5yr'; 'Dec25_3 5yr'; 'Notes'};
k = oe_release_sort_key(names);
assert(isequal(size(k), [5 3]) && all(isnan(k(5, :))));
[~, order] = sortrows(k(1:4, :), [-1 -2 -3]);
assert(isequal(names(order), {'Mar26_10 5yr'; 'Mar26_2 5yr'; 'Jan26_1 5yr'; 'Dec25_3 5yr'}), ...
    'release numbers must sort numerically (10 after 2)');
end

function test_resolve_release_offline()
R = table({'Jan26_1 5yr'; 'Mar26_2 5yr'; 'Mar26_10 5yr'; 'Mar26_10 25yr'; 'Mar26_2 5yr'; 'Notes'}, ...
    {'root/Ext/Jan26_1 5yr'; 'root/Ext/Mar26_2 5yr'; 'root/Ext/Mar26_10 5yr'; 'root/Ext/Mar26_10 25yr'; ...
    'root/Ext/Previous releases/2026-03_2/Mar26_2 5yr'; 'root/Ext/Notes'}, ...
    {'id-1'; 'id-2'; 'id-3'; 'id-4'; 'id-5'; 'id-6'}, {'5yr'; '5yr'; '5yr'; '25yr'; '5yr'; ''}, ...
    [false; false; false; false; true; false], ...
    'VariableNames', {'name', 'path', 'id', 'horizon', 'isPrevious'});
r = oe_resolve_release('latest:5yr', R);
assert(strcmp(r.Id, 'id-3') && strcmp(r.Name, 'Mar26_10 5yr'));
r = oe_resolve_release('latest:25yr', R);
assert(strcmp(r.Id, 'id-4'));
r = oe_resolve_release('latest', R);
assert(any(strcmp(r.Id, {'id-3', 'id-4'})));
r = oe_resolve_release('mar26_2 5yr', R);
assert(strcmp(r.Id, 'id-2'), 'the current copy must win over the one under Previous releases');
% an all-zero id, built at run time so no id-like literal sits in the source
fakeId = strjoin({repmat('0', 1, 8), '0000', '0000', '0000', repmat('0', 1, 12)}, '-');
r = oe_resolve_release(fakeId);
assert(strcmp(r.Id, fakeId) && isempty(r.Path));
assert_error(@() oe_resolve_release('Nov19_1 5yr', R), 'oe:noRelease');
assert_error(@() oe_resolve_release('latest:10yr', R), 'oe:noRelease');
end

function test_token_missing()
old = getenv('OE_TOKEN');
c = onCleanup(@() setenv('OE_TOKEN', old));
setenv('OE_TOKEN', '');
err = assert_error(@() oe_token(), 'oe:noToken');
assert(contains(err.message, 'setenv(''OE_TOKEN''') && contains(err.message, '$env:OE_TOKEN') ...
    && contains(err.message, 'export OE_TOKEN'), 'the message must show how to set the token');
assert_error(@() oe_api('GET', '/v1/resources/me'), 'oe:noToken');   % fails before any request
setenv('OE_TOKEN', sprintf('  Bearer tok-123  \n'));
assert(strcmp(oe_token(), 'tok-123'));
end

function test_login_config_missing()
names = {'OE_AUTH_DOMAIN', 'OE_AUTH_CLIENT_ID', 'OE_AUTH_AUDIENCE'};
old = cellfun(@getenv, names, 'UniformOutput', false);
c = onCleanup(@() restore_env(names, old));
restore_env(names, {'', '', ''});
err = assert_error(@() oe_login('user', 'not-a-password'), 'oe:authConfig');
assert(contains(err.message, 'OE_AUTH_DOMAIN') && contains(err.message, 'account setup'));
end

function test_api_fake_transport()
old = getenv('OE_TOKEN');
c = onCleanup(@() setenv('OE_TOKEN', old));
secret = 'fake-tok-123';
setenv('OE_TOKEN', secret);
base = struct('baseUrl', 'https://api.invalid/api', 'backoff', 0, 'quiet', true);

% BOM removed, JSON decoded, path encoding and bearer header as expected
t = fake_transport({200}, {[239 187 191 double('{"Id":"x1","Name":"Toy"}')]});
out = oe_api('GET', ['/v1/resources/' oe_quote_path('toy root/a b')], [], with(base, 'transport', t.fn));
assert(isstruct(out) && strcmp(out.Id, 'x1'));
assert(strcmp(t.state('uri'), 'https://api.invalid/api/v1/resources/toy%20root/a%20b'), ...
    'unexpected URL %s', t.state('uri'));
assert(strcmp(t.state('auth'), ['Bearer ' secret]));

% JSON body: a one-element cell array is still sent as an array
t = fake_transport({200}, {double('[]')});
oe_api('POST', '/v1/x', {struct('IndicatorCode', 'AAA', 'GroupCode', 'ALPHA')}, with(base, 'transport', t.fn));
assert(strcmp(t.state('body'), '[{"IndicatorCode":"AAA","GroupCode":"ALPHA"}]'));

% transient failures are retried: 503, then a dropped connection, then success
t = fake_transport({503, 'drop', 200}, {double('busy'), [], double('[1,2]')});
out = oe_api('GET', '/v1/x', [], with(base, 'transport', t.fn));
assert(isequal(out, [1; 2]) && t.state('n') == 3);

% plain text comes back as char; an empty body as []
t = fake_transport({200}, {double('plain text')});
assert(strcmp(oe_api('GET', '/v1/x', [], with(base, 'transport', t.fn)), 'plain text'));
t = fake_transport({204}, {[]});
assert(isempty(oe_api('DELETE', '/v1/x', [], with(base, 'transport', t.fn))));

% HTTP errors carry the status in the identifier and never the token
t = fake_transport({404}, {double(['no such resource; echo Bearer ' secret])});
err = assert_error(@() oe_api('GET', '/v1/x', [], with(base, 'transport', t.fn)), 'oe:http404');
assert(contains(err.message, 'HTTP 404') && ~contains(err.message, secret));

% after the last retry a network failure is reported, again without the token
t = fake_transport({'drop'}, {[]});
err = assert_error(@() oe_api('GET', '/v1/x', [], with(with(base, 'transport', t.fn), 'retries', 2)), ...
    'oe:network');
assert(t.state('n') == 3 && ~contains(err.message, secret));
end

function test_eq_latex()
L = oe_eq_latex('DLOG(AAA:ALPHA) = 0.5 * DLOG(BBB:ALPHA[-1]) + &AAA:ALPHA');
assert(contains(L, '\Delta\log(\mathrm{AAA:ALPHA})'), 'got %s', L);
assert(contains(L, '\mathrm{BBB:ALPHA}_{t-1}'), 'got %s', L);
assert(contains(L, '\varepsilon_{\mathrm{AAA:ALPHA}}'), 'got %s', L);
assert(contains(L, '0.5 \cdot '), 'got %s', L);
L2 = oe_eq_latex('EXP(LN(CCC_X:BETA[+1])) ^ 2');
assert(contains(L2, '\exp(\log(') && contains(L2, '\mathrm{CCC\_X:BETA}_{t+1}') && contains(L2, '^{2}'), ...
    'got %s', L2);
assert(isempty(oe_eq_latex('')));
end

%% -------------------------------------------------------------- helpers

function T = long(forecast, indicator, group, periods, values)
periods = cellstr(periods);
periods = periods(:);
n = numel(periods);
freq = repmat({'Q'}, n, 1);
freq(~contains(periods, 'Q')) = {'A'};
T = table(repmat({forecast}, n, 1), repmat({indicator}, n, 1), repmat({group}, n, 1), periods, freq, ...
    values(:), repmat({'level'}, n, 1), ...
    'VariableNames', {'forecast', 'indicator', 'group', 'period', 'freq', 'value', 'measure'});
end

function v = val(T, forecast, group, period)
v = T.value(strcmp(T.forecast, forecast) & strcmp(T.group, group) & strcmp(T.period, period));
assert(isscalar(v), 'expected one row for %s %s %s, found %d', forecast, group, period, numel(v));
end

function err = assert_error(fn, id)
try
    fn();
catch err
    assert(strcmp(err.identifier, id), 'expected error %s, got %s: %s', id, err.identifier, err.message);
    return
end
error('run_tests:noError', 'expected error %s, but none was raised', id);
end

function s = with(s, name, value)
s.(name) = value;
end

function t = fake_transport(statuses, bodies)
% A stand-in for matlab.net.http send: replies with STATUSES{k} and
% BODIES{k} on the k-th call ('drop' raises a network error) and records
% the last URL, Authorization header and request body.
state = containers.Map({'n', 'uri', 'auth', 'body'}, {0, '', '', ''});
t.state = state;
t.fn = @(req, uri, ~) fake_reply(state, statuses, bodies, req, uri);
end

function resp = fake_reply(state, statuses, bodies, req, uri)
n = state('n') + 1;
state('n') = n;
state('uri') = char(string(uri));
f = getFields(req, 'Authorization');
state('auth') = char(f(1).Value);
if ~isempty(req.Body) && ~isempty(req.Body.Payload)
    % state is a containers.Map (a handle), so the write is seen by the caller
    state('body') = native2unicode(reshape(uint8(req.Body.Payload), 1, []), 'UTF-8'); %#ok<NASGU>
end
s = statuses{min(n, numel(statuses))};
if ischar(s)
    error('fake:network', 'simulated connection reset');
end
resp = struct('StatusCode', s, 'Body', struct('Payload', uint8(bodies{min(n, numel(bodies))}), 'Data', []));
end

function restore_env(names, values)
for i = 1:numel(names)
    setenv(names{i}, values{i});
end
end

function write_file(f, txt)
fid = fopen(f, 'w');
fprintf(fid, '%s', txt);
fclose(fid);
end

function delete_if(f)
if isfile(f)
    delete(f);
end
end
