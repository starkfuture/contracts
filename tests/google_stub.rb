# frozen_string_literal: true

# A stand-in for Google's token and key endpoints, for tests/google.py only. It runs inside the test
# pod (STARK_GOOGLE_TOKEN_URL / _JWKS_URL point here) and signs ID tokens with its own RSA key, so
# the fork's real verification code runs against good and bad tokens.
# The authorization code tells it what to return: "<scenario>~<nonce>".
require 'socket'
require 'json'
require 'uri'
require 'openssl'
require 'jwt'

KEY = OpenSSL::PKey::RSA.generate(2048)
OTHER_KEY = OpenSSL::PKey::RSA.generate(2048) # signs the "forged" token: valid shape, wrong key
JWK = JWT::JWK.new(KEY, kid: 'stub')
DOMAIN = ENV.fetch('STARK_GOOGLE_DOMAIN')
CLIENT = ENV.fetch('STARK_GOOGLE_CLIENT_ID')

def claims(scenario, nonce)
  now = Time.now.to_i
  base = { 'iss' => 'https://accounts.google.com', 'aud' => CLIENT, 'iat' => now, 'exp' => now + 300,
           'nonce' => nonce, 'email_verified' => true, 'hd' => DOMAIN, 'email' => "admin@#{DOMAIN}" }
  case scenario
  when 'admin' then base
  when 'newuser' then base.merge('email' => "Newbie@#{DOMAIN}", 'given_name' => 'New', 'family_name' => 'Bie')
  when 'archived' then base.merge('email' => "archived@#{DOMAIN}")
  when 'otherdomain' then base.merge('email' => 'someone@gmail.com', 'hd' => nil)
  when 'nohd' then base.merge('hd' => nil) # a consumer Google account registered on a company address
  when 'hdspoof' then base.merge('email' => 'someone@evil.example')
  when 'unverified' then base.merge('email_verified' => false)
  when 'wrongaud' then base.merge('aud' => 'someone-elses-client')
  when 'wrongiss' then base.merge('iss' => 'https://evil.example')
  when 'expired' then base.merge('iat' => now - 7200, 'exp' => now - 3600)
  when 'wrongnonce' then base.merge('nonce' => 'not-the-one')
  when /\Aas-(\w+)\z/ then base.merge('email' => "#{Regexp.last_match(1)}@#{DOMAIN}") # any company user (tests/mcp_oauth.py)
  else base
  end
end

def token_response(form)
  return [401, { error: 'invalid_client' }] unless form['client_secret'] == ENV.fetch('STARK_GOOGLE_CLIENT_SECRET')

  scenario, nonce = form['code'].to_s.split('~', 2)
  key = scenario == 'forged' ? OTHER_KEY : KEY
  [200, { id_token: JWT.encode(claims(scenario, nonce), key, 'RS256', kid: 'stub'), token_type: 'Bearer' }]
end

server = TCPServer.new('127.0.0.1', 8099)
loop do
  client = server.accept
  request_line = client.gets.to_s
  headers = {}
  while (line = client.gets) && line != "\r\n"
    k, v = line.split(':', 2)
    headers[k.downcase] = v.to_s.strip
  end
  body = client.read(headers['content-length'].to_i)
  status, payload =
    if request_line.start_with?('GET /certs') then [200, { keys: [JWK.export] }]
    elsif request_line.start_with?('POST /token') then token_response(URI.decode_www_form(body.to_s).to_h)
    else [404, { error: 'not found' }]
    end
  json = JSON.generate(payload)
  client.write("HTTP/1.1 #{status} X\r\nContent-Type: application/json\r\nContent-Length: #{json.bytesize}\r\nConnection: close\r\n\r\n#{json}")
  client.close
rescue StandardError => e
  warn "google_stub: #{e.class}: #{e.message}"
  client&.close
end
