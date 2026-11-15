-- ============================================================
-- GrowGPT (ModuleScript)
-- À placer dans ServerScriptService, sous le nom "GrowGPT"
-- Contient la connexion au serveur GrowGPT + la synchro des prix
-- ============================================================

local HttpService = game:GetService("HttpService")
local TextService = game:GetService("TextService")

local GrowGPT = {}

-- ⚙️ CONFIG — remplace par ton URL Render
-- (ce module est côté serveur : les joueurs ne peuvent pas lire le secret)
GrowGPT.URL    = "https://TON-APP.onrender.com"
GrowGPT.SECRET = "TON_SECRET"   -- même valeur que ROBLOX_SECRET dans Render (ne mets la vraie valeur que dans Roblox Studio, jamais sur GitHub)

-- ⚙️ Intervalle de synchro des prix (300 = 5 minutes)
-- Bonus : ça garde aussi le serveur Render gratuit réveillé tant qu'un serveur Roblox tourne
GrowGPT.SYNC_INTERVAL = 300

local function post(path, body)
	local ok, result = pcall(function()
		return HttpService:PostAsync(
			GrowGPT.URL .. path,
			HttpService:JSONEncode(body),
			Enum.HttpContentType.ApplicationJson
		)
	end)
	if not ok then
		warn("[GrowGPT] ❌ " .. path .. " : " .. tostring(result))
		return nil
	end
	local decoded, data = pcall(HttpService.JSONDecode, HttpService, result)
	return decoded and data or nil
end

-- ============================================================
-- Filtre Roblox : OBLIGATOIRE avant d'afficher un texte généré
-- ============================================================
function GrowGPT.Filter(text, player)
	local ok, filtered = pcall(function()
		local result = TextService:FilterStringAsync(text, player.UserId)
		return result:GetNonChatStringForBroadcastAsync()
	end)
	return ok and filtered or nil
end

-- ============================================================
-- Prix — remplace getCurrentPrices par ton vrai système de prix !
-- ============================================================
function GrowGPT.GetCurrentPrices()
	-- EXEMPLE — tu peux lire depuis un DataStore, un ModuleScript, etc.
	return {
		carrot     = math.random(8,  25),
		tomato     = math.random(30, 70),
		corn       = math.random(20, 45),
		wheat      = math.random(12, 30),
		strawberry = math.random(40, 90),
		blueberry  = math.random(50, 110),
		pumpkin    = math.random(35, 80),
		potato     = math.random(10, 28),
		rose       = math.random(60, 130),
		sunflower  = math.random(55, 120),
	}
end

function GrowGPT.SyncPrices()
	local data = post("/update_prices", { secret = GrowGPT.SECRET, prices = GrowGPT.GetCurrentPrices() })
	if data and data.ok then
		print("[GrowGPT] ✅ Prix synchronisés — " .. data.prices_received .. " plantes")
	end
end

function GrowGPT.StartPriceSync()
	task.spawn(function()
		while true do
			GrowGPT.SyncPrices()
			task.wait(GrowGPT.SYNC_INTERVAL)
		end
	end)
end

-- ============================================================
-- Chat : renvoie la réponse déjà filtrée (ou nil si échec)
-- ============================================================
function GrowGPT.Ask(player, message, playerData)
	playerData = playerData or {}
	local data = post("/growgpt", {
		player_id = tostring(player.UserId),
		message   = message,
		player    = {
			name   = player.DisplayName,
			level  = playerData.level  or 1,
			money  = playerData.money  or 0,
			plants = playerData.plants or {},
		},
	})
	if not data or not data.response then
		return nil
	end
	return GrowGPT.Filter(data.response, player)
end

-- ============================================================
-- Quêtes
-- ============================================================
function GrowGPT.GetPlayerQuests(player, playerData)
	local data = post("/quests", { player_id = tostring(player.UserId), lang = "fr", player = playerData or {} })
	if not data then
		return {}, {}
	end
	return data.suggested or {}, data.active or {}
end

function GrowGPT.AcceptQuest(player, questId)
	local data = post("/quests/create", { player_id = tostring(player.UserId), quest_id = questId, lang = "fr" })
	if not data then
		return false, "Erreur connexion"
	end
	return data.ok, data.message
end

return GrowGPT
