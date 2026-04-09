-- ============================================================
-- GrowGPT_PriceSync.lua
-- Script côté SERVEUR Roblox (ServerScript)
-- Envoie les prix au serveur GrowGPT toutes les 5 minutes
-- ============================================================

local HttpService = game:GetService("HttpService")
local RunService  = game:GetService("RunService")

-- ⚙️ CONFIG — remplace par ton URL Render
local GROWGPT_URL = "https://TON-APP.onrender.com"
local SECRET      = "TON_SECRET"   -- même valeur que ROBLOX_SECRET dans Render

-- ⚙️ Intervalle en secondes (300 = 5 minutes)
local SYNC_INTERVAL = 300

-- ============================================================
-- FONCTION : récupère les prix depuis ton système de prix Roblox
-- Remplace cette fonction par ton vrai système de prix !
-- ============================================================
local function getCurrentPrices()
    -- EXEMPLE — remplace par tes vraies valeurs de prix
    -- Tu peux lire depuis un DataStore, un ModuleScript, etc.
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

-- ============================================================
-- FONCTION : envoie les prix à GrowGPT
-- ============================================================
local function syncPrices()
    local prices = getCurrentPrices()

    local ok, result = pcall(function()
        return HttpService:PostAsync(
            GROWGPT_URL .. "/update_prices",
            HttpService:JSONEncode({
                secret = SECRET,
                prices = prices
            }),
            Enum.HttpContentType.ApplicationJson
        )
    end)

    if ok then
        local data = HttpService:JSONDecode(result)
        if data.ok then
            print("[GrowGPT] ✅ Prix synchronisés — " .. data.prices_received .. " plantes")
        else
            warn("[GrowGPT] ❌ Erreur serveur : " .. tostring(result))
        end
    else
        warn("[GrowGPT] ❌ Connexion échouée : " .. tostring(result))
    end
end

-- ============================================================
-- FONCTION : interroge GrowGPT pour un joueur
-- Appelle cette fonction depuis tes autres scripts Roblox
-- ============================================================
function AskGrowGPT(playerId, message, playerData)
    local ok, result = pcall(function()
        return HttpService:PostAsync(
            GROWGPT_URL .. "/growgpt",
            HttpService:JSONEncode({
                player_id = tostring(playerId),
                message   = message,
                lang      = "fr",    -- "fr" ou "en"
                player    = {
                    name   = playerData.name   or "Farmer",
                    level  = playerData.level  or 1,
                    money  = playerData.money  or 0,
                    plants = playerData.plants or {}
                }
            }),
            Enum.HttpContentType.ApplicationJson
        )
    end)

    if ok then
        local data = HttpService:JSONDecode(result)
        return data.response or "GrowGPT est silencieux..."
    else
        warn("[GrowGPT] ❌ Chat error: " .. tostring(result))
        return "⚠️ GrowGPT est hors ligne."
    end
end

-- ============================================================
-- FONCTION : récupère les quêtes d'un joueur
-- ============================================================
function GetPlayerQuests(playerId, playerData)
    local ok, result = pcall(function()
        return HttpService:PostAsync(
            GROWGPT_URL .. "/quests",
            HttpService:JSONEncode({
                player_id = tostring(playerId),
                lang      = "fr",
                player    = playerData
            }),
            Enum.HttpContentType.ApplicationJson
        )
    end)

    if ok then
        local data = HttpService:JSONDecode(result)
        return data.suggested or {}, data.active or {}
    else
        warn("[GrowGPT] ❌ Quests error: " .. tostring(result))
        return {}, {}
    end
end

-- ============================================================
-- FONCTION : accepter une quête
-- ============================================================
function AcceptQuest(playerId, questId)
    local ok, result = pcall(function()
        return HttpService:PostAsync(
            GROWGPT_URL .. "/quests/create",
            HttpService:JSONEncode({
                player_id = tostring(playerId),
                quest_id  = questId,
                lang      = "fr"
            }),
            Enum.HttpContentType.ApplicationJson
        )
    end)

    if ok then
        local data = HttpService:JSONDecode(result)
        return data.ok, data.message
    end
    return false, "Erreur connexion"
end

-- ============================================================
-- BOUCLE PRINCIPALE — sync toutes les 5 min
-- ============================================================

-- Sync immédiate au démarrage
syncPrices()

-- Timer
local elapsed = 0
RunService.Heartbeat:Connect(function(dt)
    elapsed += dt
    if elapsed >= SYNC_INTERVAL then
        elapsed = 0
        syncPrices()
    end
end)

print("[GrowGPT] 🌱 Price sync activé — synchronisation toutes les " .. SYNC_INTERVAL .. "s")

-- ============================================================
-- EXEMPLE D'UTILISATION dans un autre script :
-- ============================================================
-- local GrowGPT = require(script.Parent.GrowGPT_PriceSync)
--
-- -- Chat avec GrowGPT :
-- local reply = AskGrowGPT(player.UserId, "quoi planter ?", {
--     name   = player.Name,
--     level  = playerStats.Level.Value,
--     money  = playerStats.Money.Value,
--     plants = {"carrot", "tomato"}
-- })
-- print(reply)
--
-- -- Afficher les quêtes :
-- local suggested, active = GetPlayerQuests(player.UserId, playerData)
-- for _, quest in pairs(suggested) do
--     print(quest.title .. " — " .. quest.desc)
-- end
