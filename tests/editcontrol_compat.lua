-- Use the real PoB classes; substitute only foreign libraries and graphics.
package.path = './?.lua;../runtime/lua/?.lua;../runtime/lua/?/init.lua;' .. package.path
package.loaded['lcurl.safe'] = {}
package.loaded.xml = {}
package.loaded.base64 = {}
package.loaded.sha1 = {}
-- This host has no lua-utf8 library. These cases verify ASCII behavior only.
package.loaded['lua-utf8'] = string
launch = { devMode = false }
main = { unicode = true }
function ConPrintf() end
function GetTime() return 1000 end
function GetCursorPos() return 1, 1 end
function DrawStringWidth(height, font, value) return #value * height / 2 end
function NewImageHandle() return { Load = function() end } end
function LoadModule(name, ...)
    return assert(loadfile(name .. '.lua'))(...)
end
LoadModule('Modules/Common')

local ok, err = pcall(dofile, arg[1])
assert(not ok and err:match('attempt to concatenate local .className. %(a function value%)'), tostring(err))
print('old class API error reproduced')
common.classes.EditControl = nil
dofile(arg[2])

for _, case in ipairs({
    { name = 'plain', init = 'abc' },
    { name = 'numeric', init = '12', filter = '%D' },
    { name = 'clearable', init = 'abc', clearable = true },
    { name = 'multiline', init = 'abc\ndef', lineHeight = 16 },
}) do
    local control = new('EditControl'):EditControl(nil, {0, 0, 300, 60}, case.init,
        nil, case.filter, nil, nil, case.lineHeight, nil, case.clearable)
    assert(control.buf == case.init and control.caret == #case.init + 1)
    assert(control.controls.scrollBarH and control.controls.scrollBarV and control.tooltip)
    for parent in pairs(common.classes.EditControl._superParents) do
        assert(control._parentInit[parent], 'parent not initialized: ' .. parent._className)
    end
    if case.name == 'numeric' then
        assert(control.controls.buttonDown and control.controls.buttonUp)
    elseif case.name == 'clearable' then
        assert(control.controls.buttonClear)
        control.controls.buttonClear:Click()
        assert(control.buf == '')
    end
    print('constructed ' .. case.name)
end
local edit = new('EditControl'):EditControl(nil, {0, 0, 300, 60}, 'abc')
edit:Insert('d')
assert(edit.buf == 'abcd')
edit:Undo()
assert(edit.buf == 'abc')
edit:Redo()
assert(edit.buf == 'abcd')
edit:SelectAll()
edit:ReplaceSel('xyz')
assert(edit.buf == 'xyz')
print('all EditControl behavior checks passed')
