-- ============================================================
-- GrowGPT_Chat (Script)
-- À placer dans ServerScriptService, à côté du ModuleScript "GrowGPT"
-- Les joueurs parlent à l'IA en commençant leur message par "@growgpt"
-- ============================================================

local Players           = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local GrowGPT = require(script.Parent.GrowGPT)

local PREFIX   = "@growgpt"
local COOLDOWN = 5   -- secondes entre deux questions d'un même joueur (préserve le quota gratuit)

-- Événement pour afficher la réponse dans le chat des joueurs
local replyEvent = Instance.new("RemoteEvent")
replyEvent.Name = "GrowGPTReply"
replyEvent.Parent = ReplicatedStorage

-- ⚙️ Remplace par la lecture de tes vraies stats joueur
local function getPlayerData(player)
	local stats = player:FindFirstChild("leaderstats")
	return {
		level  = stats and stats:FindFirstChild("Level") and stats.Level.Value or 1,
		money  = stats and stats:FindFirstChild("Money") and stats.Money.Value or 0,
		plants = {},
	}
end

local lastAsk = {}

local function onChatted(player, message)
	if message:lower():sub(1, #PREFIX) ~= PREFIX then
		return
	end
	local question = message:sub(#PREFIX + 1):gsub("^%s+", "")
	if question == "" then
		return
	end

	local now = os.clock()
	if lastAsk[player] and now - lastAsk[player] < COOLDOWN then
		return
	end
	lastAsk[player] = now

	local reply = GrowGPT.Ask(player, question, getPlayerData(player))
	if reply then
		replyEvent:FireAllClients(reply)
	end
end

Players.PlayerAdded:Connect(function(player)
	player.Chatted:Connect(function(message)
		onChatted(player, message)
	end)
end)

Players.PlayerRemoving:Connect(function(player)
	lastAsk[player] = nil
end)

GrowGPT.StartPriceSync()
print("[GrowGPT] 🌱 Prêt — écris \"" .. PREFIX .. " ta question\" dans le chat")
