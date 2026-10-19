%% EXAMPLE_RUN  Two illustrative scenarios against the latest 5-year release.
% Run this script section by section (Ctrl+Enter). It makes real API calls:
% each solve takes a minute or two and writes a forecast into your workspace.
%
% The mnemonics below (WPO_EQN, RFED, GDP, CPI and the group codes) are
% common codes used only to show the syntax. Check every code in your own
% catalogue (step 3, or oe_catalogue) before relying on it: codes can differ
% between model versions. The shock sizes are illustrative round numbers,
% not recommendations and not model output.

%% 1. Token: once per session, never saved in a file
% Paste a token you already have:
%   setenv('OE_TOKEN', '<your token>');
% or log in, if your account setup gave you the OE_AUTH_* values:
%   oe_login('<username>', '<password>');
addpath(fileparts(mfilename('fullpath')));   % the toolkit folder

%% 2. Pick the release
rel = oe_resolve_release('latest:5yr');      % or a name, e.g. 'Sep26_2 5yr'

%% 3. Check the codes used below in the catalogue
[ind, grp] = oe_catalogue(rel);
disp(ind(ismember(ind.Code, {'WPO_EQN', 'RFED', 'GDP', 'CPI'}), {'Code', 'Name'}));
disp(grp(ismember(grp.Code, {'WORLD', 'US', 'CHINA', 'JAPAN', 'EURO_11'}), {'Code', 'Name'}));

%% 4. Define the scenarios
% Value commands (MULTIPLY, INCREASE, SET) need a FIX over the same window,
% otherwise the model recomputes the variable from its equation.
scen = struct('name', {}, 'description', {}, 'commands', {}, 'file', {});

scen(1).name = 'oil_up_20pct';
scen(1).description = 'World oil price 20% above the input forecast through 2027';
scen(1).commands = {
    'MULTIPLY WPO_EQN:WORLD 2027Q1 1.2, 1.2, 1.2, 1.2'
    'FIX WPO_EQN:WORLD 2027Q1:2027Q4'};

scen(2).name = 'us_rate_up_100bp';
scen(2).description = 'US policy rate 1 percentage point higher through 2027';
scen(2).commands = {
    'INCREASE RFED:US 2027Q1 1, 1, 1, 1'
    'FIX RFED:US 2027Q1:2027Q4'};

% A scenario can also come from a command file:
%   scen(3).name = 'my_case';  scen(3).file = 'my_case.3fs';

%% 5. Solve both scenarios and fetch baseline + scenarios
cfg = struct();
cfg.release = rel.Path;
cfg.solveFrom = '2026Q3';
cfg.solveTo = '2031Q4';
cfg.scenarios = scen;
cfg.indicators = {'GDP', 'CPI'};
cfg.groups = {'US', 'CHINA', 'JAPAN', 'EURO_11'};
cfg.from = '2025Q1';
cfg.to = '2031Q4';
cfg.runName = 'example';
cfg.outputFolder = '/me';                     % solved forecasts go to /me/example/...
cfg.outDir = fullfile(pwd, 'oe_runs', 'example');
[T, manifest] = oe_run_scenarios(cfg);

%% 6. Annual averages, growth rates and deviations from the baseline
growth = oe_transform(T, 'annual_avg|yoy');            % annual growth / inflation, %
devPP = oe_transform(growth, 'dev_abs', 'baseline');   % scenario minus baseline, pp
levelDev = oe_transform(T, 'annual_avg|dev_pct');      % % deviation of annual levels

%% 7. Tables
gdp = oe_table(devPP, 'GDP', struct('from', '2026', 'to', '2031', 'decimals', 2));
cpi = oe_table(devPP, 'CPI', struct('from', '2026', 'to', '2031', 'decimals', 2));
gdpLevel = oe_table(levelDev, 'GDP', struct('from', '2026', 'to', '2031', 'decimals', 2));
disp(gdp);
disp(cpi);
writetable(gdp, fullfile(cfg.outDir, 'gdp_growth_dev_pp.csv'));
writetable(cpi, fullfile(cfg.outDir, 'cpi_inflation_dev_pp.csv'));
writetable(gdpLevel, fullfile(cfg.outDir, 'gdp_level_dev_pct.csv'));
