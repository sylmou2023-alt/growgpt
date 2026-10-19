-- ============================================================
-- GrowGPT_Display (LocalScript)
-- À placer dans StarterPlayer > StarterPlayerScripts
-- Affiche les réponses de GrowGPT dans le chat
-- ============================================================

local ReplicatedStorage = game:GetService("ReplicatedStorage")
local TextChatService   = game:GetService("TextChatService")

local replyEvent = ReplicatedStorage:WaitForChild("GrowGPTReply")
local channel    = TextChatService:WaitForChild("TextChannels"):WaitForChild("RBXGeneral")

replyEvent.OnClientEvent:Connect(function(text)
	-- Échapper le texte pour que le rich text ne casse pas l'affichage
	text = text:gsub("&", "&amp;"):gsub("<", "&lt;"):gsub(">", "&gt;")
	channel:DisplaySystemMessage("<font color=\"#5BD15B\">[GrowGPT]</font> " .. text)
end)
