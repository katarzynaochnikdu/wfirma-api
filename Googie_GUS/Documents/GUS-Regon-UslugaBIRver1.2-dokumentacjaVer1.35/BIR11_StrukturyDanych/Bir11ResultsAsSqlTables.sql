
-- definicje tabel wynikowych dla us³ugi BIR1.1

-- 1) Metoda BIR11DaneSzukajPodmioty

	DECLARE [BIR11DaneSzukajPodmioty] table(
    Regon varchar(14) NOT NULL,
	Nip varchar(10),
	StatusNip varchar(12),
    Nazwa varchar(2000),
    Wojewodztwo varchar(200),
    Powiat varchar(200),
	Gmina varchar(200),
	Miejscowosc varchar(200),
	KodPocztowy varchar(12),
	Ulica varchar(200),
	NrNieruchomosci varchar(20),
	NrLokalu varchar(10),
	Typ varchar(2),
	SilosID int,
	DataZakonczeniaDzialalnosci varchar(10),
	MiejscowoscPoczty varchar(200)
	)

-- 2) Raporty metody DanePobierzPelnyRaport 
	
/* [BIR11OsFizycznaDaneOgolne] */

	DECLARE [BIR11OsFizycznaDaneOgolne] TABLE ( 
	[fiz_regon9] [char](9) NULL,
	[fiz_nip] [varchar](10) NULL,
	[fiz_statusNip] [varchar](12) NULL,
	[fiz_nazwisko] [varchar](100) NULL,
	[fiz_imie1] [varchar](50) NULL,
	[fiz_imie2] [varchar](50) NULL,
	[fiz_dataWpisuPodmiotuDoRegon] [varchar](10) NULL,
	[fiz_dataZaistnieniaZmiany] [varchar](10) NULL,
	[fiz_dataSkresleniaPodmiotuZRegon] [varchar](10) NULL,
	[fiz_podstawowaFormaPrawna_Symbol] [varchar](3) NULL,
	[fiz_szczegolnaFormaPrawna_Symbol] [varchar](3) NULL,
	[fiz_formaFinansowania_Symbol] [varchar](1) NULL,
	[fiz_formaWlasnosci_Symbol] [varchar](50) NULL,
	[fiz_podstawowaFormaPrawna_Nazwa] [varchar](200) NULL,
	[fiz_szczegolnaFormaPrawna_Nazwa] [varchar](200) NULL,
	[fiz_formaFinansowania_Nazwa] [varchar](240) NULL,
	[fiz_formaWlasnosci_Nazwa] [varchar](240) NULL,
	[fiz_dzialalnoscCeidg] [int] NULL,
	[fiz_dzialalnoscRolnicza] [int] NULL,
	[fiz_dzialalnoscPozostala] [int] NULL,
	[fiz_dzialalnoscSkreslonaDo20141108] [int] NULL,
	[fiz_liczbaJednLokalnych] [int] NULL )
	
	
/*  [BIR11OsFizycznaDzialalnoscCeidg] */

	DECLARE [BIR11OsFizycznaDzialalnoscCeidg] TABLE (
	[fiz_regon9] [char](9) NULL,
	[fiz_nazwa] [nvarchar](2000) NULL,
	[fiz_nazwaSkrocona] [nvarchar](256) NULL,
	[fiz_dataPowstania] [varchar](10) NULL,
	[fiz_dataRozpoczeciaDzialalnosci] [varchar](10) NULL,
	[fiz_dataWpisuDzialalnosciDoRegon] [varchar](10) NULL,
	[fiz_dataZawieszeniaDzialalnosci] [varchar](10) NULL,
	[fiz_dataWznowieniaDzialalnosci] [varchar](10) NULL,
	[fiz_dataZaistnieniaZmianyDzialalnosci] [varchar](10) NULL,
	[fiz_dataZakonczeniaDzialalnosci] [varchar](10) NULL,
	[fiz_dataSkresleniaDzialalnosciZRegon] [varchar](10) NULL,
	[fiz_dataOrzeczeniaOUpadlosci] [varchar](10) NULL,
	[fiz_dataZakonczeniaPostepowaniaUpadlosciowego] [varchar](10) NULL,
	[fiz_adSiedzKraj_Symbol] [varchar](2) NULL,
	[fiz_adSiedzWojewodztwo_Symbol] [varchar](2) NULL,
	[fiz_adSiedzPowiat_Symbol] [varchar](2) NULL,
	[fiz_adSiedzGmina_Symbol] [varchar](3) NULL,
	[fiz_adSiedzKodPocztowy] [varchar](12) NULL,
	[fiz_adSiedzMiejscowoscPoczty_Symbol] [varchar](7) NULL,
	[fiz_adSiedzMiejscowosc_Symbol] [varchar](7) NULL,
	[fiz_adSiedzUlica_Symbol] [varchar](5) NULL,
	[fiz_adSiedzNumerNieruchomosci] [varchar](20) NULL,
	[fiz_adSiedzNumerLokalu] [varchar](10) NULL,
	[fiz_adSiedzNietypoweMiejsceLokalizacji] [varchar](160) NULL,
	[fiz_numerTelefonu] [varchar](1) NULL,
	[fiz_numerWewnetrznyTelefonu] [varchar](1) NULL,
	[fiz_numerFaksu] [varchar](1) NULL,
	[fiz_adresEmail] [varchar](100) NULL,
	[fiz_adresStronyinternetowej] [varchar](100) NULL,
	[fiz_adSiedzKraj_Nazwa] [varchar](200) NULL,
	[fiz_adSiedzWojewodztwo_Nazwa] [varchar](100) NULL,
	[fiz_adSiedzPowiat_Nazwa] [varchar](100) NULL,
	[fiz_adSiedzGmina_Nazwa] [varchar](100) NULL,
	[fiz_adSiedzMiejscowosc_Nazwa] [varchar](100) NULL,
	[fiz_adSiedzMiejscowoscPoczty_Nazwa] [varchar](100) NULL,
	[fiz_adSiedzUlica_Nazwa] [varchar](351) NULL,
	[fizC_dataWpisuDoRejestruEwidencji] [varchar](10) NULL,
	[fizC_dataSkresleniaZRejestruEwidencji] [varchar](10) NULL,
	[fizC_numerWRejestrzeEwidencji] [varchar](50) NULL,
	[fizC_OrganRejestrowy_Symbol] [varchar](9) NULL,
	[fizC_OrganRejestrowy_Nazwa] [varchar](240) NULL,
	[fizC_RodzajRejestru_Symbol] [varchar](3) NULL,
	[fizC_RodzajRejestru_Nazwa] [varchar](240) NULL,
	[fizC_NiePodjetoDzialalnosci] [bit] NULL	)
	
	/* [BIR11OsFizycznaDzialalnoscPozostala] */
	
	DECLARE [BIR11OsFizycznaDzialalnoscPozostala] TABLE ( 
	[fiz_regon9] [char](9) NULL,
	[fiz_nazwa] [nvarchar](2000) NULL,
	[fiz_nazwaSkrocona] [nvarchar](256) NULL,
	[fiz_dataPowstania] [varchar](10) NULL,
	[fiz_dataRozpoczeciaDzialalnosci] [varchar](10) NULL,
	[fiz_dataWpisuDzialalnosciDoRegon] [varchar](10) NULL,
	[fiz_dataZawieszeniaDzialalnosci] [varchar](10) NULL,
	[fiz_dataWznowieniaDzialalnosci] [varchar](10) NULL,
	[fiz_dataZaistnieniaZmianyDzialalnosci] [varchar](10) NULL,
	[fiz_dataZakonczeniaDzialalnosci] [varchar](10) NULL,
	[fiz_dataSkresleniaDzialalnosciZRegon] [varchar](10) NULL,
	[fiz_dataOrzeczeniaOUpadlosci] [varchar](10) NULL,
	[fiz_dataZakonczeniaPostepowaniaUpadlosciowego] [varchar](10) NULL,
	[fiz_adSiedzKraj_Symbol] [varchar](2) NULL,
	[fiz_adSiedzWojewodztwo_Symbol] [char](2) NULL,
	[fiz_adSiedzPowiat_Symbol] [char](2) NULL,
	[fiz_adSiedzGmina_Symbol] [char](3) NULL,
	[fiz_adSiedzKodPocztowy] [varchar](12) NULL,
	[fiz_adSiedzMiejscowoscPoczty_Symbol] [char](7) NULL,
	[fiz_adSiedzMiejscowosc_Symbol] [char](7) NULL,
	[fiz_adSiedzUlica_Symbol] [varchar](5) NULL,
	[fiz_adSiedzNumerNieruchomosci] [varchar](20) NULL,
	[fiz_adSiedzNumerLokalu] [varchar](10) NULL,
	[fiz_adSiedzNietypoweMiejsceLokalizacji] [varchar](160) NULL,
	[fiz_numerTelefonu] [varchar](18) NULL,
	[fiz_numerWewnetrznyTelefonu] [varchar](6) NULL,
	[fiz_numerFaksu] [varchar](18) NULL,
	[fiz_adresEmail] [varchar](100) NULL,
	[fiz_adresStronyinternetowej] [varchar](100) NULL,
	[fiz_adSiedzKraj_Nazwa] [varchar](200) NULL,
	[fiz_adSiedzWojewodztwo_Nazwa] [varchar](100) NULL,
	[fiz_adSiedzPowiat_Nazwa] [varchar](100) NULL,
	[fiz_adSiedzGmina_Nazwa] [varchar](100) NULL,
	[fiz_adSiedzMiejscowosc_Nazwa] [varchar](100) NULL,
	[fiz_adSiedzMiejscowoscPoczty_Nazwa] [varchar](100) NULL,
	[fiz_adSiedzUlica_Nazwa] [varchar](351) NULL,
	[fizP_dataWpisuDoRejestruEwidencji] [varchar](10) NULL,
	[fizP_numerWRejestrzeEwidencji] [varchar](50) NULL,
	[fizP_OrganRejestrowy_Symbol] [varchar](9) NULL,
	[fizP_OrganRejestrowy_Nazwa] [varchar](240) NULL,
	[fizP_RodzajRejestru_Symbol] [varchar](3) NULL,
	[fizP_RodzajRejestru_Nazwa] [varchar](240) NULL)
	
	/* [BIR11OsFizycznaDzialalnoscRolnicza]  */
	
	DECLARE [BIR11OsFizycznaDzialalnoscRolnicza] TABLE ( 
	[fiz_regon9] [char](9) NULL,
	[fiz_nazwa] [nvarchar](2000) NULL,
	[fiz_nazwaSkrocona] [nvarchar](256) NULL,
	[fiz_dataPowstania] [varchar](10) NULL,
	[fiz_dataRozpoczeciaDzialalnosci] [varchar](10) NULL,
	[fiz_dataWpisuDzialalnosciDoRegon] [varchar](10) NULL,
	[fiz_dataZawieszeniaDzialalnosci] [varchar](10) NULL,
	[fiz_dataWznowieniaDzialalnosci] [varchar](10) NULL,
	[fiz_dataZaistnieniaZmianyDzialalnosci] [varchar](10) NULL,
	[fiz_dataZakonczeniaDzialalnosci] [varchar](10) NULL,
	[fiz_dataSkresleniaDzialalanosciZRegon] [varchar](10) NULL,
	[fiz_dataOrzeczeniaOUpadlosci] [varchar](10) NULL,
	[fiz_dataZakonczeniaPostepowaniaUpadlosciowego] [varchar](10) NULL,
	[fiz_adSiedzKraj_Symbol] [varchar](2) NULL,
	[fiz_adSiedzWojewodztwo_Symbol] [varchar](2) NULL,
	[fiz_adSiedzPowiat_Symbol] [varchar](2) NULL,
	[fiz_adSiedzGmina_Symbol] [varchar](3) NULL,
	[fiz_adSiedzKodPocztowy] [varchar](12) NULL,
	[fiz_adSiedzMiejscowoscPoczty_Symbol] [varchar](7) NULL,
	[fiz_adSiedzMiejscowosc_Symbol] [varchar](7) NULL,
	[fiz_adSiedzUlica_Symbol] [varchar](5) NULL,
	[fiz_adSiedzNumerNieruchomosci] [varchar](20) NULL,
	[fiz_adSiedzNumerLokalu] [varchar](10) NULL,
	[fiz_adSiedzNietypoweMiejsceLokalizacji] [varchar](160) NULL,
	[fiz_numerTelefonu] [varchar](18) NULL,
	[fiz_numerWewnetrznyTelefonu] [varchar](6) NULL,
	[fiz_numerFaksu] [varchar](18) NULL,
	[fiz_adresEmail] [varchar](100) NULL,
	[fiz_adresStronyinternetowej] [varchar](100) NULL,
	[fiz_adSiedzKraj_Nazwa] [varchar](200) NULL,
	[fiz_adSiedzWojewodztwo_Nazwa] [varchar](100) NULL,
	[fiz_adSiedzPowiat_Nazwa] [varchar](100) NULL,
	[fiz_adSiedzGmina_Nazwa] [varchar](100) NULL,
	[fiz_adSiedzMiejscowosc_Nazwa] [varchar](100) NULL,
	[fiz_adSiedzMiejscowoscPoczty_Nazwa] [varchar](100) NULL,
	[fiz_adSiedzUlica_Nazwa] [varchar](351) NULL ) 

/*  [BIR11OsFizycznaDzialalnoscSkreslonaDo20141108] */	

	DECLARE [BIR11OsFizycznaDzialalnoscSkreslonaDo20141108] TABLE ( 
	[fiz_regon9] [char](9) NULL,
	[fiz_nazwa] [nvarchar](2000) NULL,
	[fiz_nazwaSkrocona] [varchar](256) NULL,
	[fiz_dataPowstania] [varchar](10) NULL,
	[fiz_dataRozpoczeciaDzialalnosci] [varchar](10) NULL,
	[fiz_dataWpisuDzialalnosciDoRegon] [varchar](10) NULL,
	[fiz_dataZawieszeniaDzialalnosci] [varchar](10) NULL,
	[fiz_dataWznowieniaDzialalnosci] [varchar](10) NULL,
	[fiz_dataZaistnieniaZmianyDzialalnosci] [varchar](10) NULL,
	[fiz_dataZakonczeniaDzialalnosci] [varchar](10) NULL,
	[fiz_dataSkresleniaDzialalnosciZRegon] [varchar](10) NULL,
	[fiz_adSiedzKraj_Symbol] [varchar](2) NULL,
	[fiz_adSiedzWojewodztwo_Symbol] [varchar](2) NULL,
	[fiz_adSiedzPowiat_Symbol] [varchar](2) NULL,
	[fiz_adSiedzGmina_Symbol] [varchar](3) NULL,
	[fiz_adSiedzKodPocztowy] [varchar](12) NULL,
	[fiz_adSiedzMiejscowoscPoczty_Symbol] [varchar](7) NULL,
	[fiz_adSiedzMiejscowosc_Symbol] [varchar](7) NULL,
	[fiz_adSiedzUlica_Symbol] [varchar](5) NULL,
	[fiz_adSiedzNumerNieruchomosci] [varchar](20) NULL,
	[fiz_adSiedzNumerLokalu] [varchar](10) NULL,
	[fiz_adSiedzNietypoweMiejsceLokalizacji] [varchar](160) NULL,
	[fiz_numerTelefonu] [varchar](18) NULL,
	[fiz_numerWewnetrznyTelefonu] [varchar](6) NULL,
	[fiz_numerFaksu] [varchar](18) NULL,
	[fiz_adresEmail] [varchar](100) NULL,
	[fiz_adresStronyinternetowej] [varchar](100) NULL,
	[fiz_adresEmail2] [varchar](100) NULL,
	[fiz_adSiedzKraj_Nazwa] [varchar](200) NULL,
	[fiz_adSiedzWojewodztwo_Nazwa] [varchar](100) NULL,
	[fiz_adSiedzPowiat_Nazwa] [varchar](100) NULL,
	[fiz_adSiedzGmina_Nazwa] [varchar](100) NULL,
	[fiz_adSiedzMiejscowosc_Nazwa] [varchar](100) NULL,
	[fiz_adSiedzMiejscowoscPoczty_Nazwa] [varchar](100) NULL,
	[fiz_adSiedzUlica_Nazwa] [varchar](351) NULL )
	
	
	/* [BIR11OsFizycznaListaJednLokalnych] */
	
	DECLARE [BIR11OsFizycznaListaJednLokalnych] TABLE (
	[lokfiz_regon14] [char](14) NULL,
	[lokfiz_nazwa] [varchar](2000) NULL,
	[lokfiz_silosID] [int] NULL,
	[lokfiz_silos_Symbol] [varchar](10) NULL,
	[lokfiz_adSiedzKraj_Symbol] [varchar](2) NULL,
	[lokfiz_adSiedzWojewodztwo_Symbol] [char](2) NULL,
	[lokfiz_adSiedzPowiat_Symbol] [char](2) NULL,
	[lokfiz_adSiedzGmina_Symbol] [char](3) NULL,
	[lokfiz_adSiedzKodPocztowy] [varchar](12) NULL,
	[lokfiz_adSiedzMiejscowoscPoczty_Symbol] [char](7) NULL,
	[lokfiz_adSiedzMiejscowosc_Symbol] [char](7) NULL,
	[lokfiz_adSiedzUlica_Symbol] [varchar](5) NULL,
	[lokfiz_adSiedzNumerNieruchomosci] [varchar](20) NULL,
	[lokfiz_adSiedzNumerLokalu] [varchar](10) NULL,
	[lokfiz_adSiedzNietypoweMiejsceLokalizacji] [varchar](256) NULL,
	[lokfiz_adSiedzWojewodztwo_Nazwa] [varchar](100) NULL,
	[lokfiz_adSiedzPowiat_Nazwa] [varchar](100) NULL,
	[lokfiz_adSiedzGmina_Nazwa] [varchar](100) NULL,
	[lokfiz_adSiedzMiejscowosc_Nazwa] [varchar](100) NULL,
	[lokfiz_adSiedzMiejscowoscPoczty_Nazwa] [varchar](100) NULL,
	[lokfiz_adSiedzUlica_Nazwa] [varchar](350) NULL,
	[lokfiz_dataPowstania] [varchar](10) NULL,
	[lokfiz_dataRozpoczeciaDzialalnosci] [varchar](10) NULL,
	[lokfiz_dataWpisuDoRegon] [varchar](10) NULL,
	[lokfiz_dataZawieszeniaDzialalnosci] [varchar](10) NULL,
	[lokfiz_dataWznowieniaDzialalnosci] [varchar](10) NULL,
	[lokfiz_dataZakonczeniaDzialalnosci] [varchar](10) NULL,
	[lokfiz_dataSkresleniaZRegon] [varchar](10) NULL )
	
	/* [BIR11OsFizycznaPkd] */
	
	DECLARE [BIR11OsFizycznaPkd] TABLE ( 
	[fiz_pkd_Kod] [varchar](5) NULL,
	[fiz_pkd_Nazwa] [varchar](200) NULL,
	[fiz_pkd_Przewazajace] [varchar](1) NULL,
	[fiz_SilosID] [int] NULL,
	[fiz_Silos_Symbol] [varchar](10) NULL,
	[fiz_dataSkresleniaDzialalnosciZRegon] [varchar](10) NULL )
	
	/* [BIR11OsPrawna] */
	
	DECLARE [BIR11OsPrawna] TABLE ( 
	[praw_regon9] [char](9) NULL,
	[praw_nip] [varchar](10) NULL,
	[praw_statusNip] [varchar](12) NULL,
	[praw_nazwa] [varchar](2000) NULL,
	[praw_nazwaSkrocona] [varchar](256) NULL,
	[praw_numerWRejestrzeEwidencji] [varchar](50) NULL,
	[praw_dataWpisuDoRejestruEwidencji] [varchar](10) NULL,
	[praw_dataPowstania] [varchar](10) NULL,
	[praw_dataRozpoczeciaDzialalnosci] [varchar](10) NULL,
	[praw_dataWpisuDoRegon] [varchar](10) NULL,
	[praw_dataZawieszeniaDzialalnosci] [varchar](10) NULL,
	[praw_dataWznowieniaDzialalnosci] [varchar](10) NULL,
	[praw_dataZaistnieniaZmiany] [varchar](10) NULL,
	[praw_dataZakonczeniaDzialalnosci] [varchar](10) NULL,
	[praw_dataSkresleniaZRegon] [varchar](10) NULL,
	[praw_dataOrzeczeniaOUpadlosci] [varchar](10) NULL,
	[praw_dataZakonczeniaPostepowaniaUpadlosciowego] [varchar](10) NULL,
	[praw_adSiedzKraj_Symbol] [varchar](2) NULL,
	[praw_adSiedzWojewodztwo_Symbol] [varchar](2) NULL,
	[praw_adSiedzPowiat_Symbol] [varchar](2) NULL,
	[praw_adSiedzGmina_Symbol] [varchar](3) NULL,
	[praw_adSiedzKodPocztowy] [varchar](12) NULL,
	[praw_adSiedzMiejscowoscPoczty_Symbol] [varchar](7) NULL,
	[praw_adSiedzMiejscowosc_Symbol] [varchar](7) NULL,
	[praw_adSiedzUlica_Symbol] [varchar](5) NULL,
	[praw_adSiedzNumerNieruchomosci] [varchar](20) NULL,
	[praw_adSiedzNumerLokalu] [varchar](10) NULL,
	[praw_adSiedzNietypoweMiejsceLokalizacji] [varchar](160) NULL,
	[praw_numerTelefonu] [varchar](18) NULL,
	[praw_numerWewnetrznyTelefonu] [varchar](6) NULL,
	[praw_numerFaksu] [varchar](18) NULL,
	[praw_adresEmail] [varchar](100) NULL,
	[praw_adresStronyinternetowej] [varchar](100) NULL,
	[praw_adSiedzKraj_Nazwa] [varchar](200) NULL,
	[praw_adSiedzWojewodztwo_Nazwa] [varchar](100) NULL,
	[praw_adSiedzPowiat_Nazwa] [varchar](100) NULL,
	[praw_adSiedzGmina_Nazwa] [varchar](100) NULL,
	[praw_adSiedzMiejscowosc_Nazwa] [varchar](100) NULL,
	[praw_adSiedzMiejscowoscPoczty_Nazwa] [varchar](100) NULL,
	[praw_adSiedzUlica_Nazwa] [varchar](351) NULL,
	[praw_podstawowaFormaPrawna_Symbol] [varchar](3) NULL,
	[praw_szczegolnaFormaPrawna_Symbol] [varchar](3) NULL,
	[praw_formaFinansowania_Symbol] [varchar](1) NULL,
	[praw_formaWlasnosci_Symbol] [varchar](50) NULL,
	[praw_organZalozycielski_Symbol] [varchar](9) NULL,
	[praw_organRejestrowy_Symbol] [varchar](9) NULL,
	[praw_rodzajRejestruEwidencji_Symbol] [varchar](3) NULL,
	[praw_podstawowaFormaPrawna_Nazwa] [varchar](200) NULL,
	[praw_szczegolnaFormaPrawna_Nazwa] [varchar](200) NULL,
	[praw_formaFinansowania_Nazwa] [varchar](240) NULL,
	[praw_formaWlasnosci_Nazwa] [varchar](240) NULL,
	[praw_organZalozycielski_Nazwa] [varchar](200) NULL,
	[praw_organRejestrowy_Nazwa] [varchar](240) NULL,
	[praw_rodzajRejestruEwidencji_Nazwa] [varchar](240) NULL,
	[praw_liczbaJednLokalnych] [int] NULL) 
	
	/*  [BIR11OsPrawnaListaJednLokalnych] */
	
	DECLARE [BIR11OsPrawnaListaJednLokalnych] TABLE ( 
	[lokpraw_regon14] [char](14) NULL,
	[lokpraw_nazwa] [varchar](254) NULL,
	[lokpraw_adSiedzKraj_Symbol] [varchar](2) NULL,
	[lokpraw_adSiedzWojewodztwo_Symbol] [char](2) NULL,
	[lokpraw_adSiedzPowiat_Symbol] [char](2) NULL,
	[lokpraw_adSiedzGmina_Symbol] [char](3) NULL,
	[lokpraw_adSiedzKodPocztowy] [varchar](12) NULL,
	[lokpraw_adSiedzMiejscowoscPoczty_Symbol] [char](7) NULL,
	[lokpraw_adSiedzMiejscowosc_Symbol] [char](7) NULL,
	[lokpraw_adSiedzUlica_Symbol] [varchar](5) NULL,
	[lokpraw_adSiedzNumerNieruchomosci] [varchar](20) NULL,
	[lokpraw_adSiedzNumerLokalu] [varchar](10) NULL,
	[lokpraw_adSiedzNietypoweMiejsceLokalizacji] [varchar](160) NULL,
	[lokpraw_adSiedzWojewodztwo_Nazwa] [varchar](100) NULL,
	[lokpraw_adSiedzPowiat_Nazwa] [varchar](100) NULL,
	[lokpraw_adSiedzGmina_Nazwa] [varchar](100) NULL,
	[lokpraw_adSiedzMiejscowosc_Nazwa] [varchar](100) NULL,
	[lokpraw_adSiedzMiejscowoscPoczty_Nazwa] [varchar](100) NULL,
	[lokpraw_adSiedzUlica_Nazwa] [varchar](351) NULL,
	[lokpraw_dataPowstania] [varchar](10) NULL,
	[lokpraw_dataRozpoczeciaDzialalnosci] [varchar](10) NULL,
	[lokpraw_dataWpisuDoRegon] [varchar](10) NULL,
	[lokpraw_dataZawieszeniaDzialalnosci] [varchar](10) NULL,
	[lokpraw_dataWznowieniaDzialalnosci] [varchar](10) NULL,
	[lokpraw_dataZakonczeniaDzialalnosci] [varchar](10) NULL,
	[lokpraw_dataSkresleniaZRegon] [varchar](10) NULL )
	
	/* [BIR11OsPrawnaPkd] */
	
		DECLARE [BIR11OsPrawnaPkd] TABLE ( 
		[praw_pkdKod] [varchar](5) NULL,
		[praw_pkdNazwa] [varchar](200) NULL,
		[praw_pkdPrzewazajace] [varchar](1) NULL ) 
		
		/* [BIR11OsPrawnaSpCywilnaWspolnicy] */
		
			DECLARE [BIR11OsPrawnaSpCywilnaWspolnicy] TABLE ( 
	[wspolsc_regonWspolnikSpolki] [char](9) NULL,
	[wspolsc_imiePierwsze] [varchar](30) NULL,
	[wspolsc_imieDrugie] [varchar](30) NULL,
	[wspolsc_nazwisko] [varchar](40) NULL,
	[wspolsc_firmaNazwa] [varchar](2000) NULL) 
	
	/* [BIR11JednLokalnaOsFizycznej] */
	
	DECLARE [BIR11JednLokalnaOsFizycznej] TABLE ( 
	[lokfiz_regon14] [char](14) NULL,
	[lokfiz_nazwa] [varchar](2000) NULL,
	[lokfiz_silosID] [int] NULL,
	[lokfiz_silos_Nazwa] [varchar](10) NULL,
	[lokfiz_dataPowstania] [varchar](10) NULL,
	[lokfiz_dataRozpoczeciaDzialalnosci] [varchar](10) NULL,
	[lokfiz_dataWpisuDoRegon] [varchar](10) NULL,
	[lokfiz_dataZawieszeniaDzialalnosci] [varchar](10) NULL,
	[lokfiz_dataWznowieniaDzialalnosci] [varchar](10) NULL,
	[lokfiz_dataZaistnieniaZmiany] [varchar](10) NULL,
	[lokfiz_dataZakonczeniaDzialalnosci] [varchar](10) NULL,
	[lokfiz_dataSkresleniaZRegon] [varchar](10) NULL,
	[lokfiz_adSiedzKraj_Symbol] [varchar](2) NULL,
	[lokfiz_adSiedzWojewodztwo_Symbol] [char](2) NULL,
	[lokfiz_adSiedzPowiat_Symbol] [char](2) NULL,
	[lokfiz_adSiedzGmina_Symbol] [char](3) NULL,
	[lokfiz_adSiedzKodPocztowy] [varchar](12) NULL,
	[lokfiz_adSiedzMiejscowoscPoczty_Symbol] [char](7) NULL,
	[lokfiz_adSiedzMiejscowosc_Symbol] [char](7) NULL,
	[lokfiz_adSiedzUlica_Symbol] [varchar](5) NULL,
	[lokfiz_adSiedzNumerNieruchomosci] [varchar](20) NULL,
	[lokfiz_adSiedzNumerLokalu] [varchar](10) NULL,
	[lokfiz_adSiedzNietypoweMiejsceLokalizacji] [varchar](256) NULL,
	[lokfiz_adSiedzKraj_Nazwa] [varchar](200) NULL,
	[lokfiz_adSiedzWojewodztwo_Nazwa] [varchar](100) NULL,
	[lokfiz_adSiedzPowiat_Nazwa] [varchar](100) NULL,
	[lokfiz_adSiedzGmina_Nazwa] [varchar](100) NULL,
	[lokfiz_adSiedzMiejscowosc_Nazwa] [varchar](100) NULL,
	[lokfiz_adSiedzMiejscowoscPoczty_Nazwa] [varchar](100) NULL,
	[lokfiz_adSiedzUlica_Nazwa] [varchar](350) NULL,	
	[lokfiz_FormaFinansowania_Nazwa] [varchar](240) NULL,
	[lokfiz_FormaFinansowania_Symbol] [varchar](1) NULL,
	[lokfiz_dataWpisuDoRejestruEwidencji] [varchar](30) NULL,
	[lokfiz_numerwRejestrzeEwidencji] [varchar](50) NULL,
	[lokfiz_OrganRejestrowy_Symbol] [varchar](9) NULL,
	[lokfiz_RodzajRejestru_Symbol] [varchar](3) NULL,
	[lokfiz_OrganRejestrowy_Nazwa] [varchar](240) NULL,
	[lokfiz_RodzajRejestru_Nazwa] [varchar](240) NULL,
	[lokfizC_NiePodjetoDzialalnosci] [bit] NULL)
		
	
	/* [BIR11JednLokalnaOsFizycznejPkd] */	
	
  DECLARE [BIR11JednLokalnaOsFizycznejPkd] TABLE ( 
	[lokfiz_pkd_Kod] [varchar](5) NULL,
	[lokfiz_pkd_Nazwa] [varchar](200) NULL,
	[lokfiz_pkd_Przewazajace] [varchar](1) NULL,
	[lokfiz_Silos_Symbol] [varchar](10) NULL)

	
	/* [BIR11JednLokalnaOsPrawnej] */
	
	DECLARE [BIR11JednLokalnaOsPrawnej] TABLE ( 
	[lokpraw_regon14] [char](14) NULL,
	[lokpraw_nazwa] [varchar](254) NULL,
	[lokpraw_numerWrejestrzeEwidencji] [varchar](50) NULL,
	[lokpraw_dataWpisuDoRejestruEwidencji] [varchar](10) NULL,
	[lokpraw_dataPowstania] [varchar](10) NULL,
	[lokpraw_dataRozpoczeciaDzialalnosci] [varchar](10) NULL,
	[lokpraw_dataWpisuDoRegon] [varchar](10) NULL,
	[lokpraw_dataZawieszeniaDzialalnosci] [varchar](10) NULL,
	[lokpraw_dataWznowieniaDzialalnosci] [varchar](10) NULL,
	[lokpraw_dataZaistnieniaZmiany] [varchar](10) NULL,
	[lokpraw_dataZakonczeniaDzialalnosci] [varchar](10) NULL,
	[lokpraw_dataSkresleniaZRegon] [varchar](10) NULL,
	[lokpraw_adSiedzKraj_Symbol] [varchar](2) NULL,
	[lokpraw_adSiedzWojewodztwo_Symbol] [varchar](2) NULL,
	[lokpraw_adSiedzPowiat_Symbol] [varchar](2) NULL,
	[lokpraw_adSiedzGmina_Symbol] [varchar](3) NULL,
	[lokpraw_adSiedzKodPocztowy] [varchar](12) NULL,
	[lokpraw_adSiedzMiejscowoscPoczty_Symbol] [varchar](7) NULL,
	[lokpraw_adSiedzMiejscowosc_Symbol] [varchar](7) NULL,
	[lokpraw_adSiedzUlica_Symbol] [varchar](5) NULL,
	[lokpraw_adSiedzNumerNieruchomosci] [varchar](20) NULL,
	[lokpraw_adSiedzNumerLokalu] [varchar](10) NULL,
	[lokpraw_adSiedzNietypoweMiejsceLokalizacji] [varchar](160) NULL,
	[lokpraw_adSiedzKraj_Nazwa] [varchar](200) NULL,
	[lokpraw_adSiedzWojewodztwo_Nazwa] [varchar](100) NULL,
	[lokpraw_adSiedzPowiat_Nazwa] [varchar](100) NULL,
	[lokpraw_adSiedzGmina_Nazwa] [varchar](100) NULL,
	[lokpraw_adSiedzMiejscowosc_Nazwa] [varchar](100) NULL,
	[lokpraw_adSiedzMiejscowoscPoczty_Nazwa] [varchar](100) NULL,
	[lokpraw_adSiedzUlica_Nazwa] [varchar](351) NULL,
	[lokpraw_formaFinansowania_Symbol] [varchar](1) NULL,
	[lokpraw_organRejestrowy_Symbol] [varchar](9) NULL,
	[lokpraw_rodzajRejestruEwidencji_Symbol] [varchar](3) NULL,
	[lokpraw_formaFinansowania_Nazwa] [varchar](240) NULL,
	[lokpraw_organRejestrowy_Nazwa] [varchar](240) NULL,
	[lokpraw_rodzajRejestruEwidencji_Nazwa] [varchar](240) NULL)
	
	
	/* [BIR11JednLokalnaOsPrawnejPkd] */
	
	DECLARE [BIR11JednLokalnaOsPrawnejPkd] TABLE ( 
	[lokpraw_pkdKod] [varchar](5) NULL,
	[lokpraw_pkdNazwa] [varchar](200) NULL,
	[lokpraw_pkdPrzewazajace] [varchar](1) NULL)
	
	/*	BIR11TypPodmiotu */
	
	DECLARE [BIR11TypPodmiotu] TABLE ( 
	[Typ] [varchar](2) NULL )
	
	
	
	
